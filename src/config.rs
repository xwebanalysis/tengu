use serde::Deserialize;
use std::time::Duration;

// ---------------------------------------------------------------------------
// Per-request audit options (from WebSocket query params)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct AuditOptions {
    pub url: String,
    #[serde(default)]
    pub mode: String,
    #[serde(default)]
    pub subdomains: bool,
    #[serde(default = "default_checks")]
    pub checks: String,
    #[serde(default)]
    pub batch_url: String,
    #[serde(default)]
    pub batch_format: String,
}

fn default_checks() -> String {
    "performance,seo,accessibility,best_practices".to_string()
}

impl AuditOptions {
    pub fn has_check(&self, name: &str) -> bool {
        self.checks.split(',').any(|c| c.trim() == name)
    }

    pub fn is_full_site(&self) -> bool {
        self.mode == "fullsite"
    }

    pub fn is_batch(&self) -> bool {
        self.mode == "batch"
    }
}

// ---------------------------------------------------------------------------
// Global server configuration (from environment variables)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct TenguConfig {
    pub port: u16,
    pub static_dir: String,
    pub max_history: usize,
    pub api_key: Option<String>,

    pub http_timeout_secs: u64,
    pub http_max_redirects: usize,
    pub http_retry_count: u32,
    pub http_user_agent: String,

    pub rate_limit_per_minute: f64,
    pub rate_limit_burst: u32,

    pub max_concurrent_audits: usize,

    pub database_url: Option<String>,
    pub db_path: String,

    pub cors_origins: Vec<String>,

    pub crawl_delay_min_ms: u64,
    pub crawl_delay_max_ms: u64,
    pub max_crawl_pages: usize,
    pub crawl_depth: usize,
    pub crawl_respect_robots: bool,
}

impl TenguConfig {
    pub fn from_env() -> Self {
        let max_crawl_pages = env_var("TENGU_MAX_PAGES")
            .and_then(|v| v.parse().ok())
            .unwrap_or(50);
        let crawl_depth = env_var("TENGU_CRAWL_DEPTH")
            .and_then(|v| v.parse().ok())
            .unwrap_or(2);
        let crawl_delay_min_ms = env_var("TENGU_CRAWL_DELAY_MIN_MS")
            .and_then(|v| v.parse().ok())
            .unwrap_or(200);
        let crawl_delay_max_ms = env_var("TENGU_CRAWL_DELAY_MAX_MS")
            .and_then(|v| v.parse().ok())
            .unwrap_or(800);

        // Token bucket: 120 req/min by default (XWA suite standard).
        // `TENGU_RATE_LIMIT_PER_SECOND` is kept as a legacy alias.
        let rate_limit_per_minute = env_var("TENGU_RATE_LIMIT_PER_MINUTE")
            .and_then(|v| v.parse().ok())
            .or_else(|| {
                env_var("TENGU_RATE_LIMIT_PER_SECOND")
                    .and_then(|v| v.parse::<f64>().ok())
                    .map(|per_sec| per_sec * 60.0)
            })
            .unwrap_or(120.0);

        Self {
            port: env_var("PORT").and_then(|v| v.parse().ok()).unwrap_or(8070),
            static_dir: env_var("STATIC_DIR").unwrap_or_else(|| "static/browser".into()),
            max_history: env_var("TENGU_MAX_HISTORY")
                .and_then(|v| v.parse().ok())
                .unwrap_or(100),
            api_key: env_var("TENGU_API_KEY").filter(|s| !s.is_empty()),

            http_timeout_secs: env_var("TENGU_HTTP_TIMEOUT")
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),
            http_max_redirects: env_var("TENGU_HTTP_MAX_REDIRECTS")
                .and_then(|v| v.parse().ok())
                .unwrap_or(10),
            http_retry_count: env_var("TENGU_HTTP_RETRY")
                .and_then(|v| v.parse().ok())
                .unwrap_or(2),
            http_user_agent: env_var("TENGU_USER_AGENT").unwrap_or_else(|| {
                format!(
                    "Tengu/{} (+https://github.com/xwebanalysis/tengu)",
                    env!("CARGO_PKG_VERSION")
                )
            }),

            rate_limit_per_minute,
            rate_limit_burst: env_var("TENGU_RATE_LIMIT_BURST")
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),

            max_concurrent_audits: env_var("TENGU_MAX_CONCURRENT")
                .and_then(|v| v.parse().ok())
                .unwrap_or(3),

            database_url: env_var("DATABASE_URL").filter(|s| !s.is_empty()),
            db_path: env_var("TENGU_DB_PATH").unwrap_or_else(|| "tengu.db".into()),

            cors_origins: env_var("XWA_CORS_ORIGINS")
                .map(|raw| {
                    raw.split(',')
                        .map(|o| o.trim().to_string())
                        .filter(|o| !o.is_empty())
                        .collect()
                })
                .unwrap_or_default(),

            crawl_delay_min_ms: crawl_delay_min_ms.min(crawl_delay_max_ms),
            crawl_delay_max_ms,
            max_crawl_pages: max_crawl_pages.max(1),
            crawl_depth,
            crawl_respect_robots: env_var("TENGU_ROBOTS_TXT")
                .map(|v| v != "0" && !v.eq_ignore_ascii_case("false"))
                .unwrap_or(true),
        }
    }

    pub fn version(&self) -> &'static str {
        env!("CARGO_PKG_VERSION")
    }

    pub fn http_timeout(&self) -> Duration {
        Duration::from_secs(self.http_timeout_secs.max(1))
    }

    pub fn http_client_builder(&self) -> reqwest::ClientBuilder {
        reqwest::Client::builder()
            .user_agent(&self.http_user_agent)
            .timeout(self.http_timeout())
            .redirect(reqwest::redirect::Policy::limited(self.http_max_redirects))
    }
}

fn env_var(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn audit_options_helpers() {
        let opts = AuditOptions {
            url: "example.com".into(),
            mode: "fullsite".into(),
            subdomains: false,
            checks: "performance, seo".into(),
            batch_url: String::new(),
            batch_format: String::new(),
        };
        assert!(opts.has_check("seo"));
        assert!(!opts.has_check("accessibility"));
        assert!(opts.is_full_site());
        assert!(!opts.is_batch());
    }

    #[test]
    fn http_client_builder_is_constructible() {
        let cfg = TenguConfig::from_env();
        assert!(cfg.http_client_builder().build().is_ok());
        assert!(cfg.http_timeout() >= Duration::from_secs(1));
    }
}
