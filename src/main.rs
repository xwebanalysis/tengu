use axum::{
    body::Body,
    extract::{Request, State},
    http::{header, HeaderValue, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{delete, get, post},
    Json, Router,
};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tower_http::cors::{AllowOrigin, Any, CorsLayer};

mod api;
mod auditor;
mod config;
mod contracts;
mod storage;

#[derive(Clone)]
pub struct AppState {
    pub store: storage::AuditStore,
    pub config: config::TenguConfig,
    pub rate_limiter: Arc<RateLimiter>,
    pub request_count: Arc<AtomicU32>,
    pub audit_semaphore: Arc<tokio::sync::Semaphore>,
}

// ---------------------------------------------------------------------------
// Token bucket rate limiter (XWA default: 120 req/min)
// ---------------------------------------------------------------------------

pub struct RateLimiter {
    max_burst: f64,
    tokens_per_second: f64,
    state: Mutex<RateState>,
}

struct RateState {
    tokens: f64,
    last_time: Instant,
}

impl RateLimiter {
    pub fn new(per_minute: f64, burst: u32) -> Self {
        Self {
            max_burst: burst.max(1) as f64,
            tokens_per_second: (per_minute.max(1.0)) / 60.0,
            state: Mutex::new(RateState {
                tokens: burst.max(1) as f64,
                last_time: Instant::now(),
            }),
        }
    }

    pub fn check(&self) -> bool {
        self.check_at(Instant::now())
    }

    /// Deterministic variant used by unit tests.
    fn check_at(&self, now: Instant) -> bool {
        let mut state = match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => poisoned.into_inner(),
        };
        let elapsed = now.duration_since(state.last_time).as_secs_f64();
        state.tokens = (state.tokens + elapsed * self.tokens_per_second).min(self.max_burst);
        state.last_time = now;
        if state.tokens >= 1.0 {
            state.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}

// ---------------------------------------------------------------------------
// Middlewares
// ---------------------------------------------------------------------------

async fn auth_middleware(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let path = req.uri().path().to_string();
    if !path.starts_with("/api/") || path == "/api/health" || path == "/api/metrics" {
        return next.run(req).await;
    }

    let Some(expected_key) = state.config.api_key.as_deref() else {
        return next.run(req).await;
    };

    let header_key = req
        .headers()
        .get("x-api-key")
        .and_then(|v| v.to_str().ok())
        .map(str::to_string)
        .or_else(|| {
            req.headers()
                .get(header::AUTHORIZATION)
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.strip_prefix("Bearer "))
                .map(str::to_string)
        });

    // Legacy query-string compatibility; docs recommend the header.
    let query_key = req.uri().query().and_then(|q| {
        q.split('&')
            .filter_map(|pair| pair.strip_prefix("api_key="))
            .next()
            .map(|value| value.to_string())
    });

    let provided = header_key.or(query_key);

    match provided {
        Some(key) if constant_time_eq(&key, expected_key) => next.run(req).await,
        _ => {
            let body = serde_json::json!({
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Unauthorized. Provide the X-API-Key header.",
                    "detail": null,
                    "retryable": false
                }
            });
            Response::builder()
                .status(StatusCode::UNAUTHORIZED)
                .header(header::WWW_AUTHENTICATE, "Bearer")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(body.to_string()))
                .unwrap_or_else(|_| StatusCode::UNAUTHORIZED.into_response())
        }
    }
}

fn constant_time_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.bytes().zip(b.bytes()) {
        diff |= x ^ y;
    }
    diff == 0
}

async fn rate_limit_middleware(
    State(state): State<AppState>,
    req: Request,
    next: Next,
) -> Response {
    state.request_count.fetch_add(1, Ordering::Relaxed);

    let path = req.uri().path();
    let is_preflight = req.method() == axum::http::Method::OPTIONS;
    if path == "/api/health" || is_preflight {
        return next.run(req).await;
    }

    if state.rate_limiter.check() {
        next.run(req).await
    } else {
        let body = serde_json::json!({
            "error": {
                "code": "RATE_LIMITED",
                "message": "Rate limit exceeded. Retry later.",
                "detail": null,
                "retryable": true
            }
        });
        Response::builder()
            .status(StatusCode::TOO_MANY_REQUESTS)
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::RETRY_AFTER, "1")
            .body(Body::from(body.to_string()))
            .unwrap_or_else(|_| StatusCode::TOO_MANY_REQUESTS.into_response())
    }
}

// ---------------------------------------------------------------------------
// CORS (XWA standard: `XWA_CORS_ORIGINS`, credentials disabled)
// ---------------------------------------------------------------------------

fn is_local_or_lan_origin(origin: &HeaderValue) -> bool {
    let Ok(origin) = origin.to_str() else {
        return false;
    };
    let host_port = origin
        .strip_prefix("https://")
        .or_else(|| origin.strip_prefix("http://"));
    let Some(host_port) = host_port else {
        return false;
    };
    let host = host_port
        .split('/')
        .next()
        .unwrap_or("")
        .trim_start_matches('[')
        .split(']')
        .next()
        .unwrap_or("");
    let host_no_port = if host.contains("::") {
        host
    } else {
        host.split(':').next().unwrap_or(host)
    };

    if host_no_port == "localhost" || host_no_port == "127.0.0.1" || host_no_port == "::1" {
        return true;
    }
    let octets: Vec<&str> = host_no_port.split('.').collect();
    if octets.len() == 4 {
        if octets[0] == "10" || (octets[0] == "192" && octets[1] == "168") {
            return true;
        }
        if octets[0] == "172" {
            if let Ok(second) = octets[1].parse::<u8>() {
                return (16..=31).contains(&second);
            }
        }
    }
    false
}

fn cors_layer(cfg: &config::TenguConfig) -> CorsLayer {
    let layer = CorsLayer::new()
        .allow_methods(Any)
        .allow_headers(Any)
        .allow_credentials(false);

    if cfg.cors_origins.is_empty() {
        layer.allow_origin(AllowOrigin::predicate(|origin, _parts| {
            is_local_or_lan_origin(origin)
        }))
    } else {
        let origins: Vec<HeaderValue> = cfg
            .cors_origins
            .iter()
            .filter_map(|origin| origin.parse().ok())
            .collect();
        layer.allow_origin(origins)
    }
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

#[derive(serde::Serialize)]
struct HealthResponse {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    database: &'static str,
}

async fn health(State(state): State<AppState>) -> impl IntoResponse {
    let ok = state.store.healthcheck().await;
    let status = if ok { "ok" } else { "error" };
    let body = HealthResponse {
        status,
        service: "tengu",
        version: state.config.version(),
        database: status,
    };
    let code = if ok {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };
    (code, Json(body))
}

async fn metrics_handler(State(state): State<AppState>) -> impl IntoResponse {
    let count = state.request_count.load(Ordering::Relaxed);
    let store_count = state.store.count().await;
    (
        StatusCode::OK,
        [("Content-Type", "text/plain; charset=utf-8")],
        format!(
            "# HELP tengu_requests_total Total HTTP requests\n\
             # TYPE tengu_requests_total counter\n\
             tengu_requests_total {}\n\
             \n\
             # HELP tengu_audits_total Total audits in store\n\
             # TYPE tengu_audits_total gauge\n\
             tengu_audits_total {}\n\
             \n\
             # HELP tengu_database_backend Active persistence backend\n\
             # TYPE tengu_database_backend gauge\n\
             tengu_database_backend{{backend=\"{}\"}} 1\n",
            count,
            store_count,
            state.store.kind().as_str(),
        ),
    )
}

async fn fallback(State(state): State<AppState>, req: Request<Body>) -> impl IntoResponse {
    let static_dir = state.config.static_dir.clone();
    let path = req.uri().path();

    let file_path = if path == "/" {
        format!("{}/index.html", static_dir)
    } else {
        let candidate = format!("{}{}", static_dir, path);
        if tokio::fs::metadata(&candidate).await.is_ok() {
            candidate
        } else {
            format!("{}/index.html", static_dir)
        }
    };

    let ext = file_path.rsplit('.').next().unwrap_or("");
    let content_type = match ext {
        "html" => "text/html; charset=utf-8",
        "js" => "application/javascript",
        "css" => "text/css",
        "json" => "application/json",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "ttf" => "font/ttf",
        "txt" => "text/plain",
        _ => "application/octet-stream",
    };

    let is_text = matches!(ext, "html" | "js" | "css" | "json" | "svg" | "txt");

    let contents = if is_text {
        tokio::fs::read_to_string(&file_path).await.map(Body::from)
    } else {
        tokio::fs::read(&file_path).await.map(Body::from)
    };

    match contents {
        Ok(body) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, content_type)
            .body(body)
            .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response()),
        Err(_) if path == "/" => {
            let body = serde_json::json!({
                "status": "ok",
                "service": "tengu",
                "version": state.config.version(),
                "database": state.store.kind().as_str(),
            });
            (StatusCode::OK, Json(body)).into_response()
        }
        Err(_) => Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Body::from("Not found"))
            .unwrap_or_else(|_| StatusCode::NOT_FOUND.into_response()),
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "tengu=info,tower_http=info".into()),
        )
        .init();

    let cfg = config::TenguConfig::from_env();

    let store = storage::create_store(&cfg).await;
    tracing::info!("Persistence backend: {}", store.kind().as_str());

    let state = AppState {
        store,
        config: cfg.clone(),
        rate_limiter: Arc::new(RateLimiter::new(
            cfg.rate_limit_per_minute,
            cfg.rate_limit_burst,
        )),
        request_count: Arc::new(AtomicU32::new(0)),
        audit_semaphore: Arc::new(tokio::sync::Semaphore::new(cfg.max_concurrent_audits)),
    };

    let api_routes = Router::new()
        .route("/api/health", get(health))
        .route("/api/metrics", get(metrics_handler))
        .route("/api/audits", get(api::routes::list_audits))
        .route("/api/audits/clear", delete(api::routes::clear_all_audits))
        .route("/api/audits/export", get(api::routes::export_audits))
        .route("/api/audits/import", post(api::routes::import_audits))
        .route(
            "/api/audits/{id}",
            get(api::routes::get_audit).delete(api::routes::delete_audit),
        )
        .route("/api/analyses", get(api::routes::list_analyses))
        .route(
            "/api/analyses/{id}",
            get(api::routes::get_analysis).delete(api::routes::delete_analysis),
        )
        .route(
            "/api/analyses/{id}/export",
            get(api::routes::export_analysis),
        )
        .route("/api/audit/live", get(api::routes::audit_live))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            rate_limit_middleware,
        ))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth_middleware,
        ));

    let app = api_routes
        .layer(cors_layer(&cfg))
        .fallback(fallback)
        .with_state(state);

    let addr = format!("0.0.0.0:{}", cfg.port);
    tracing::info!("Tengu listening on {}", addr);

    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(listener) => listener,
        Err(e) => {
            tracing::error!("Failed to bind {}: {}", addr, e);
            std::process::exit(1);
        }
    };
    if let Err(e) = axum::serve(listener, app).await {
        tracing::error!("Server error: {}", e);
        std::process::exit(1);
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn rate_limiter_allows_burst_then_blocks_and_refills() {
        let limiter = RateLimiter::new(60.0, 2); // 1 token/s, burst 2
        let start = Instant::now();
        assert!(limiter.check_at(start));
        assert!(limiter.check_at(start));
        assert!(!limiter.check_at(start));
        assert!(limiter.check_at(start + Duration::from_millis(1100)));
    }

    #[test]
    fn rate_limiter_never_exceeds_burst() {
        let limiter = RateLimiter::new(600.0, 3); // 10 tokens/s, burst 3
        let now = Instant::now() + Duration::from_secs(10);
        // A long idle period refills at most `burst` tokens.
        assert!(limiter.check_at(now));
        assert!(limiter.check_at(now));
        assert!(limiter.check_at(now));
        assert!(!limiter.check_at(now));
    }

    #[test]
    fn cors_predicate_allows_localhost_and_lan() {
        let origin = |value: &str| HeaderValue::from_str(value).unwrap();
        assert!(is_local_or_lan_origin(&origin("http://localhost:4200")));
        assert!(is_local_or_lan_origin(&origin("https://127.0.0.1")));
        assert!(is_local_or_lan_origin(&origin("http://192.168.1.50:8070")));
        assert!(is_local_or_lan_origin(&origin("http://172.16.0.4")));
        assert!(!is_local_or_lan_origin(&origin("https://evil.example")));
        assert!(!is_local_or_lan_origin(&origin("http://172.32.0.1")));
        assert!(!is_local_or_lan_origin(&origin("ftp://localhost")));
    }

    #[test]
    fn constant_time_eq_works() {
        assert!(constant_time_eq("secret", "secret"));
        assert!(!constant_time_eq("secret", "secrez"));
        assert!(!constant_time_eq("secret", "secret-longer"));
    }
}
