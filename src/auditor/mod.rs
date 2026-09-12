use axum::extract::ws::{self, WebSocket};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet, VecDeque};
use std::time::Duration;
use url::Url;

use crate::config::{AuditOptions, TenguConfig};
use crate::contracts::{self, Error as ContractError, Event, EventType, Summary, Tool};

pub mod a11y;
pub mod best_practices;
pub mod html_pretty;
pub mod performance;
pub mod seo;

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

fn normalize_url(url: &str) -> String {
    let trimmed = url.trim();
    if trimmed.starts_with("http://") || trimmed.starts_with("https://") {
        trimmed.to_string()
    } else {
        format!("https://{}", trimmed)
    }
}

fn random_seed() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

/// Random delay between crawl requests (min..=max ms), seeded for testability.
pub(crate) fn jittered_delay(min_ms: u64, max_ms: u64, seed: u128) -> Duration {
    let min = min_ms.min(max_ms);
    let max = max_ms.max(min_ms);
    if max <= min {
        return Duration::from_millis(min);
    }
    let span = (max - min) as u128 + 1;
    Duration::from_millis(min + (seed % span) as u64)
}

/// Exponential backoff with jitter, capped at 5s.
pub(crate) fn backoff_delay(attempt: u32, seed: u128) -> Duration {
    let base = 250u64.saturating_mul(1u64 << attempt.min(4)).min(5_000);
    let jitter = (seed % (base as u128 / 2 + 1)) as u64;
    Duration::from_millis(base.saturating_add(jitter).min(5_000))
}

/// GET with real retry/backoff. Retries transport errors and 5xx/429.
pub(crate) async fn fetch_with_retry(
    client: &reqwest::Client,
    url: &str,
    retries: u32,
) -> Result<reqwest::Response, String> {
    let mut last_error: Option<String> = None;
    for attempt in 0..=retries {
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status();
                let retryable =
                    status.is_server_error() || status == reqwest::StatusCode::TOO_MANY_REQUESTS;
                if retryable && attempt < retries {
                    last_error = Some(format!("HTTP {status}"));
                } else {
                    return Ok(resp);
                }
            }
            Err(e) => {
                last_error = Some(e.to_string());
                if attempt >= retries {
                    break;
                }
            }
        }
        tokio::time::sleep(backoff_delay(attempt, random_seed())).await;
    }
    Err(format!(
        "Failed to fetch {} after {} attempt(s): {}",
        url,
        retries + 1,
        last_error.unwrap_or_default()
    ))
}

// ---------------------------------------------------------------------------
// XWA Event emitter (xwa-sdk Event envelope over WebSocket)
// ---------------------------------------------------------------------------

pub struct EventEmitter<'a> {
    socket: &'a mut WebSocket,
    pub analysis_id: String,
    seq: i64,
}

impl<'a> EventEmitter<'a> {
    pub fn new(socket: &'a mut WebSocket, analysis_id: String) -> Self {
        Self {
            socket,
            analysis_id,
            seq: 0,
        }
    }

    async fn emit(&mut self, event_type: EventType, payload: Option<Value>) {
        self.seq += 1;
        let event = Event {
            seq: self.seq,
            event_type,
            tool: Tool::Tengu,
            analysis_id: self.analysis_id.clone(),
            ts: chrono::Utc::now().to_rfc3339(),
            payload,
        };
        let text = serde_json::to_string(&event).unwrap_or_default();
        let _ = self.socket.send(ws::Message::Text(text.into())).await;
    }

    pub async fn started(&mut self, target: &str, mode: &str) {
        self.emit(
            EventType::AnalysisStarted,
            Some(json!({"target": target, "mode": mode})),
        )
        .await;
    }

    pub async fn progress(&mut self, message: impl Into<String>, percent: Option<f64>) {
        let mut payload = json!({"message": message.into()});
        if let Some(percent) = percent {
            payload["percent"] = json!(percent.clamp(0.0, 100.0));
        }
        self.emit(EventType::AnalysisProgress, Some(payload)).await;
    }

    pub async fn log(&mut self, level: &str, message: &str, data: Option<Value>) {
        let mut payload = json!({"level": level, "message": message});
        if let Some(data) = data {
            payload["data"] = data;
        }
        self.emit(EventType::Log, Some(payload)).await;
    }

    pub async fn item_found(&mut self, finding: &crate::auditor::Finding) {
        let contract = contracts::finding_from_tengu(finding);
        self.emit(
            EventType::ItemFound,
            Some(serde_json::to_value(contract).unwrap_or(Value::Null)),
        )
        .await;
    }

    pub async fn completed(&mut self, findings: &[crate::auditor::Finding]) {
        let contracts: Vec<contracts::Finding> =
            findings.iter().map(contracts::finding_from_tengu).collect();
        let summary = Summary::from_findings(&contracts);
        self.emit(
            EventType::AnalysisCompleted,
            Some(json!({"status": "COMPLETED", "summary": summary})),
        )
        .await;
    }

    pub async fn error(&mut self, code: &str, message: &str, retryable: bool) {
        let error = ContractError {
            code: code.to_string(),
            message: message.to_string(),
            detail: None,
            retryable,
        };
        self.emit(
            EventType::AnalysisError,
            Some(serde_json::to_value(error).unwrap_or(Value::Null)),
        )
        .await;
    }
}

pub(crate) fn error_code(message: &str) -> &'static str {
    let lower = message.to_lowercase();
    if lower.contains("invalid url") || lower.contains("invalid target") {
        "INVALID_TARGET"
    } else if lower.contains("robots") {
        "ROBOTS_DENIED"
    } else if lower.contains("timeout") || lower.contains("timed out") {
        "TIMEOUT"
    } else if lower.contains("fetch") || lower.contains("network") || lower.contains("dns") {
        "NETWORK_ERROR"
    } else {
        "INTERNAL"
    }
}

// ---------------------------------------------------------------------------
// Audit orchestration
// ---------------------------------------------------------------------------

pub async fn run_audit(
    options: &AuditOptions,
    emitter: &mut EventEmitter<'_>,
    cfg: &TenguConfig,
) -> Result<Vec<Finding>, String> {
    let mut all_findings = Vec::new();
    let opts = AuditOptions {
        url: normalize_url(&options.url),
        ..options.clone()
    };

    let pages = if opts.is_batch() {
        let batch_source = if !opts.batch_url.is_empty() {
            opts.batch_url.clone()
        } else {
            opts.url.clone()
        };

        emitter
            .progress(format!("Fetching batch URLs from {batch_source}..."), None)
            .await;

        let discovered = fetch_batch_urls(&batch_source, &opts.batch_format, cfg).await?;
        emitter
            .progress(format!("Found {} URLs in batch", discovered.len()), None)
            .await;
        discovered
    } else if opts.is_full_site() {
        emitter
            .progress(format!("Crawling {} for pages...", opts.url), None)
            .await;
        let discovered = crawl_site(&opts.url, opts.subdomains, cfg, emitter).await?;
        emitter
            .progress(format!("Found {} pages to analyze", discovered.len()), None)
            .await;
        discovered
    } else {
        vec![opts.url.clone()]
    };

    let total = pages.len().max(1);
    for (index, page_url) in pages.iter().enumerate() {
        // Respectful pacing between page fetches.
        if index > 0 {
            let delay = jittered_delay(
                cfg.crawl_delay_min_ms,
                cfg.crawl_delay_max_ms,
                random_seed(),
            );
            tokio::time::sleep(delay).await;
        }

        let percent = ((index + 1) as f64 / total as f64) * 100.0;
        emitter
            .progress(format!("Analyzing {page_url}"), Some(percent))
            .await;

        match analyze_page(page_url, &opts, emitter, cfg).await {
            Ok(mut findings) => all_findings.append(&mut findings),
            Err(e) => {
                emitter
                    .progress(format!("Error on {page_url}: {e}"), Some(percent))
                    .await;
            }
        }
    }

    Ok(all_findings)
}

// ---------------------------------------------------------------------------
// robots.txt (RFC 9309, simplified)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct RobotsRules {
    pub allow: Vec<String>,
    pub disallow: Vec<String>,
    pub crawl_delay_secs: Option<u64>,
}

impl RobotsRules {
    fn allow_all() -> Self {
        Self::default()
    }

    fn deny_all() -> Self {
        Self {
            allow: Vec::new(),
            disallow: vec!["/".to_string()],
            crawl_delay_secs: None,
        }
    }
}

#[derive(Debug, Default)]
struct RawRobotsGroup {
    agents: Vec<String>,
    allow: Vec<String>,
    disallow: Vec<String>,
    crawl_delay_secs: Option<u64>,
}

/// Parse `robots.txt` and keep the most specific matching group.
pub(crate) fn parse_robots_txt(text: &str, user_agent: &str) -> RobotsRules {
    let ua_lower = user_agent.to_ascii_lowercase();
    let mut groups: Vec<RawRobotsGroup> = Vec::new();
    let mut current: Option<RawRobotsGroup> = None;
    let mut last_was_agent = false;

    for raw in text.lines() {
        let line = raw.split('#').next().unwrap_or("").trim();
        if line.is_empty() {
            continue;
        }
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        let key = key.trim().to_ascii_lowercase();
        let value = value.trim().to_string();

        match key.as_str() {
            "user-agent" => {
                if !last_was_agent || current.is_none() {
                    if let Some(group) = current.take() {
                        groups.push(group);
                    }
                    current = Some(RawRobotsGroup::default());
                }
                if let Some(group) = current.as_mut() {
                    group.agents.push(value.to_ascii_lowercase());
                }
                last_was_agent = true;
            }
            "allow" | "disallow" => {
                if let Some(group) = current.as_mut() {
                    if key == "allow" {
                        group.allow.push(value);
                    } else {
                        group.disallow.push(value);
                    }
                }
                last_was_agent = false;
            }
            "crawl-delay" => {
                if let Some(group) = current.as_mut() {
                    group.crawl_delay_secs = value.parse().ok();
                }
                last_was_agent = false;
            }
            _ => {
                last_was_agent = false;
            }
        }
    }
    if let Some(group) = current {
        groups.push(group);
    }

    // Specific UA group wins over `*`.
    let specific = groups.iter().find(|g| {
        g.agents
            .iter()
            .any(|a| a != "*" && ua_lower.contains(a.as_str()))
    });
    let selected: Vec<&RawRobotsGroup> = if let Some(group) = specific {
        vec![group]
    } else {
        groups
            .iter()
            .filter(|g| g.agents.iter().any(|a| a == "*"))
            .collect()
    };

    let mut rules = RobotsRules::default();
    for group in selected {
        rules.allow.extend(group.allow.iter().cloned());
        rules.disallow.extend(group.disallow.iter().cloned());
        if rules.crawl_delay_secs.is_none() {
            rules.crawl_delay_secs = group.crawl_delay_secs;
        }
    }
    rules
}

fn robots_pattern_matches(pattern: &str, path: &str) -> bool {
    if pattern.is_empty() {
        return false;
    }
    let anchored_end = pattern.ends_with('$');
    let pattern = pattern.trim_end_matches('$');
    let parts: Vec<&str> = pattern.split('*').collect();
    if parts.len() == 1 {
        return if anchored_end {
            path == pattern
        } else {
            path.starts_with(pattern)
        };
    }
    if !path.starts_with(parts[0]) {
        return false;
    }
    let mut pos = parts[0].len();
    for (index, part) in parts.iter().enumerate().skip(1) {
        let last = index == parts.len() - 1;
        if part.is_empty() {
            if last && anchored_end {
                return true;
            }
            continue;
        }
        if last && anchored_end {
            return path[pos..].ends_with(part);
        }
        match path[pos..].find(part) {
            Some(found) => pos += found + part.len(),
            None => return false,
        }
    }
    true
}

/// Longest-match wins; `Allow` wins ties (RFC 9309).
pub(crate) fn robots_allows(rules: &RobotsRules, path: &str) -> bool {
    let mut decision: Option<(usize, bool)> = None;
    for pattern in &rules.disallow {
        if robots_pattern_matches(pattern, path) && !pattern.is_empty() {
            let len = pattern.len();
            if decision.is_none_or(|(best, _)| len > best) {
                decision = Some((len, false));
            }
        }
    }
    for pattern in &rules.allow {
        if robots_pattern_matches(pattern, path) {
            let len = pattern.len();
            if decision.is_none_or(|(best, _)| len >= best) {
                decision = Some((len, true));
            }
        }
    }
    decision.map(|(_, allow)| allow).unwrap_or(true)
}

fn robots_path(url: &Url) -> String {
    match url.query() {
        Some(query) => format!("{}?{}", url.path(), query),
        None => url.path().to_string(),
    }
}

async fn robots_rules_for(
    client: &reqwest::Client,
    url: &Url,
    cache: &mut HashMap<String, RobotsRules>,
    cfg: &TenguConfig,
) -> RobotsRules {
    let origin = format!("{}://{}", url.scheme(), url.host_str().unwrap_or(""));
    if let Some(rules) = cache.get(&origin) {
        return rules.clone();
    }

    let robots_url = format!("{origin}/robots.txt");
    let rules = match fetch_with_retry(client, &robots_url, cfg.http_retry_count).await {
        Ok(response) => {
            let status = response.status();
            if status.is_success() {
                match response.text().await {
                    Ok(text) => parse_robots_txt(&text, &cfg.http_user_agent),
                    Err(_) => RobotsRules::allow_all(),
                }
            } else if status == reqwest::StatusCode::NOT_FOUND {
                RobotsRules::allow_all()
            } else if status == reqwest::StatusCode::UNAUTHORIZED
                || status == reqwest::StatusCode::FORBIDDEN
            {
                RobotsRules::deny_all()
            } else {
                RobotsRules::allow_all()
            }
        }
        Err(e) => {
            tracing::debug!("robots.txt unavailable for {}: {}", origin, e);
            RobotsRules::allow_all()
        }
    };

    cache.insert(origin, rules.clone());
    rules
}

// ---------------------------------------------------------------------------
// Full-site crawl
// ---------------------------------------------------------------------------

/// Decide whether a link belongs to the crawl scope and normalize it.
pub(crate) fn is_crawlable_link(
    base: &Url,
    href: &str,
    include_subdomains: bool,
) -> Option<String> {
    let mut absolute = base.join(href).ok()?;
    if !matches!(absolute.scheme(), "http" | "https") {
        return None;
    }
    let base_host = base.host_str()?;
    let host = absolute.host_str()?.to_string();
    if include_subdomains {
        let bare = base_host.trim_start_matches("www.");
        let same = host == base_host
            || host.ends_with(&format!(".{base_host}"))
            || host.ends_with(&format!(".{bare}"));
        if !same {
            return None;
        }
    } else if host != base_host {
        return None;
    }
    absolute.set_fragment(None);
    Some(absolute.to_string())
}

async fn crawl_site(
    entry_url: &str,
    include_subdomains: bool,
    cfg: &TenguConfig,
    emitter: &mut EventEmitter<'_>,
) -> Result<Vec<String>, String> {
    let client = cfg
        .http_client_builder()
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let base_url = Url::parse(entry_url).map_err(|e| format!("Invalid URL: {e}"))?;

    let mut discovered: Vec<String> = Vec::new();
    let mut visited: HashSet<String> = HashSet::new();
    let mut queue: VecDeque<(String, usize)> = VecDeque::new();
    let mut robots_cache: HashMap<String, RobotsRules> = HashMap::new();
    queue.push_back((entry_url.to_string(), 0));

    while let Some((current, depth)) = queue.pop_front() {
        if discovered.len() >= cfg.max_crawl_pages {
            emitter
                .progress(
                    format!(
                        "Page limit reached (TENGU_MAX_PAGES={})",
                        cfg.max_crawl_pages
                    ),
                    None,
                )
                .await;
            break;
        }
        if visited.contains(&current) {
            continue;
        }

        let current_url =
            Url::parse(&current).map_err(|e| format!("Invalid URL {current}: {e}"))?;

        if cfg.crawl_respect_robots {
            let rules = robots_rules_for(&client, &current_url, &mut robots_cache, cfg).await;
            if !robots_allows(&rules, &robots_path(&current_url)) {
                if discovered.is_empty() {
                    return Err(format!("robots.txt disallows crawling {current}"));
                }
                emitter
                    .progress(format!("Skipping {current} (robots.txt)"), None)
                    .await;
                continue;
            }
        }

        visited.insert(current.clone());

        if !discovered.is_empty() {
            tokio::time::sleep(jittered_delay(
                cfg.crawl_delay_min_ms,
                cfg.crawl_delay_max_ms,
                random_seed(),
            ))
            .await;
        }

        discovered.push(current.clone());
        emitter.progress(format!("[PAGE] {current}"), None).await;

        if depth >= cfg.crawl_depth {
            continue;
        }

        let response = match fetch_with_retry(&client, &current, cfg.http_retry_count).await {
            Ok(response) => response,
            Err(e) => {
                emitter
                    .progress(format!("Failed to fetch {current}: {e}"), None)
                    .await;
                continue;
            }
        };
        let body = match response.text().await {
            Ok(body) => body,
            Err(e) => {
                emitter
                    .progress(format!("Failed to read {current}: {e}"), None)
                    .await;
                continue;
            }
        };

        let document = scraper::Html::parse_document(&body);
        let link_sel = scraper::Selector::parse("a[href]").map_err(|_| "Invalid selector")?;
        for link in document.select(&link_sel) {
            if let Some(href) = link.value().attr("href") {
                if let Some(url_str) = is_crawlable_link(&base_url, href, include_subdomains) {
                    if !visited.contains(&url_str)
                        && !queue.iter().any(|(queued, _)| queued == &url_str)
                        && discovered.len() + queue.len() < cfg.max_crawl_pages
                    {
                        queue.push_back((url_str, depth + 1));
                    }
                }
            }
        }
    }

    Ok(discovered)
}

// ---------------------------------------------------------------------------
// Batch sources
// ---------------------------------------------------------------------------

async fn fetch_batch_urls(
    batch_url: &str,
    format: &str,
    cfg: &TenguConfig,
) -> Result<Vec<String>, String> {
    let client = cfg
        .http_client_builder()
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let response = fetch_with_retry(&client, batch_url, cfg.http_retry_count)
        .await
        .map_err(|e| format!("Failed to fetch batch source: {e}"))?;

    let body = response
        .text()
        .await
        .map_err(|e| format!("Failed to read batch response: {e}"))?;

    let urls = if format == "csv" || batch_url.ends_with(".csv") {
        parse_csv_urls(&body)
    } else {
        let parsed = parse_sitemap_urls(&body);
        if parsed.is_empty() {
            let csv_urls = parse_csv_urls(&body);
            if !csv_urls.is_empty() {
                csv_urls
            } else {
                body.lines()
                    .map(|l| l.trim().to_string())
                    .filter(|l| !l.is_empty() && !l.starts_with('#'))
                    .collect()
            }
        } else {
            parsed
        }
    };

    if urls.is_empty() {
        return Err("No URLs found in batch source".into());
    }

    Ok(urls)
}

async fn analyze_page(
    page_url: &str,
    options: &AuditOptions,
    emitter: &mut EventEmitter<'_>,
    cfg: &TenguConfig,
) -> Result<Vec<Finding>, String> {
    let client = cfg
        .http_client_builder()
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let response = fetch_with_retry(&client, page_url, cfg.http_retry_count)
        .await
        .map_err(|e| format!("Failed to fetch URL: {e}"))?;

    let status = response.status();
    let headers = response.headers().clone();
    let html = response
        .text()
        .await
        .map_err(|e| format!("Failed to read response body: {e}"))?;

    emitter
        .progress(format!("{page_url} (HTTP {status})"), None)
        .await;

    let mut all_findings = Vec::new();
    let audit_html = html_pretty::pretty_print(&html);

    if options.has_check("performance") {
        let mut findings = performance::analyze(&audit_html, &headers).await;
        for f in &mut findings {
            f.page_url = Some(page_url.to_string());
            emitter.item_found(f).await;
        }
        all_findings.append(&mut findings);
    }

    if options.has_check("seo") {
        let mut findings = seo::analyze(&audit_html, page_url).await;
        for f in &mut findings {
            f.page_url = Some(page_url.to_string());
            emitter.item_found(f).await;
        }
        all_findings.append(&mut findings);

        seo::analyze_seo_network(page_url, &audit_html, &mut all_findings).await;
        for f in all_findings.iter_mut().filter(|f| {
            f.page_url.is_none()
                && (f.check == "robots_txt"
                    || f.check == "sitemap"
                    || f.check == "broken_links"
                    || f.check == "redirect_chain")
        }) {
            f.page_url = Some(page_url.to_string());
            emitter.item_found(f).await;
        }
    }

    if options.has_check("accessibility") {
        let mut findings = a11y::analyze(&audit_html).await;
        for f in &mut findings {
            f.page_url = Some(page_url.to_string());
            emitter.item_found(f).await;
        }
        all_findings.append(&mut findings);
    }

    if options.has_check("best_practices") {
        let mut findings = best_practices::analyze(&audit_html, &headers, page_url).await;
        for f in &mut findings {
            f.page_url = Some(page_url.to_string());
            emitter.item_found(f).await;
        }
        all_findings.append(&mut findings);
    }

    emitter
        .log("debug", "html_source", Some(json!({ "html": audit_html })))
        .await;

    Ok(all_findings)
}

fn parse_sitemap_urls(xml: &str) -> Vec<String> {
    let doc = scraper::Html::parse_document(xml);
    let loc_sel = scraper::Selector::parse("loc").unwrap();
    let mut urls = Vec::new();
    for el in doc.select(&loc_sel) {
        let url = el.text().collect::<String>().trim().to_string();
        if !url.is_empty() && !urls.contains(&url) {
            urls.push(url);
        }
    }
    urls
}

fn parse_csv_urls(csv: &str) -> Vec<String> {
    let mut urls = Vec::new();
    for line in csv.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let first_col = trimmed.split(',').next().unwrap_or("").trim().to_string();
        if !first_col.is_empty()
            && (first_col.starts_with("http://") || first_col.starts_with("https://"))
            && !urls.contains(&first_col)
        {
            urls.push(first_col);
        }
    }
    urls
}

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Finding {
    pub category: String,
    pub check: String,
    pub severity: Severity,
    pub title: String,
    pub description: String,
    pub snippet: Option<String>,
    pub page_url: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    Pass,
    Info,
    Warning,
    Error,
}

// ---------------------------------------------------------------------------
// Tests (pure logic, no network)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn robots_parser_matches_wildcard_group() {
        let robots = "\
User-agent: *\n\
Disallow: /private\n\
Allow: /private/public\n\
Crawl-delay: 2\n\
\n\
User-agent: badbot\n\
Disallow: /\n";
        let rules = parse_robots_txt(robots, "Tengu/0.2.0");
        assert!(robots_allows(&rules, "/"));
        assert!(robots_allows(&rules, "/private/public/page"));
        assert!(!robots_allows(&rules, "/private/secret"));
        assert_eq!(rules.crawl_delay_secs, Some(2));
    }

    #[test]
    fn robots_parser_prefers_specific_agent() {
        let robots = "\
User-agent: *\n\
Disallow: /\n\
\n\
User-agent: tengu\n\
Disallow: /admin\n\
Allow: /\n";
        let rules = parse_robots_txt(robots, "Tengu/0.2.0 (+https://xwa.dev)");
        assert!(robots_allows(&rules, "/"));
        assert!(robots_allows(&rules, "/blog"));
        assert!(!robots_allows(&rules, "/admin"));
    }

    #[test]
    fn robots_wildcards_and_end_anchor() {
        let rules = parse_robots_txt("User-agent: *\nDisallow: /*.pdf$\nAllow: /docs/\n", "tengu");
        assert!(!robots_allows(&rules, "/files/report.pdf"));
        assert!(robots_allows(&rules, "/files/report.pdf.html"));
        // `/*.pdf$` is longer/more specific than `/docs/`, so it wins (RFC 9309).
        assert!(!robots_allows(&rules, "/docs/report.pdf"));
    }

    #[test]
    fn jittered_delay_stays_in_bounds() {
        for seed in [0u128, 1, 42, 999_999] {
            let delay = jittered_delay(200, 800, seed).as_millis();
            assert!((200..=800).contains(&delay), "delay out of range: {delay}");
        }
        assert_eq!(jittered_delay(500, 500, 123).as_millis(), 500);
    }

    #[test]
    fn backoff_is_bounded_and_grows() {
        let first = backoff_delay(0, 0).as_millis();
        let second = backoff_delay(1, 0).as_millis();
        assert!((250..=5_000).contains(&first));
        assert!(second > first);
        assert!(backoff_delay(10, u128::MAX).as_millis() <= 5_000);
    }

    #[test]
    fn crawlable_links_are_scoped_to_host() {
        let base = Url::parse("https://example.com/blog").unwrap();
        assert_eq!(
            is_crawlable_link(&base, "/about#team", false).as_deref(),
            Some("https://example.com/about")
        );
        assert_eq!(is_crawlable_link(&base, "https://other.com/x", false), None);
        assert_eq!(
            is_crawlable_link(&base, "mailto:x@example.com", false),
            None
        );
        assert_eq!(
            is_crawlable_link(&base, "https://sub.example.com/page", true).as_deref(),
            Some("https://sub.example.com/page")
        );
        assert_eq!(
            is_crawlable_link(&base, "https://sub.example.com/page", false),
            None
        );
    }

    #[test]
    fn csv_and_sitemap_parsing() {
        let csv = "# comment\nhttps://a.example,\nhttps://b.example,extra\nnot-a-url\nhttps://a.example\n";
        assert_eq!(
            parse_csv_urls(csv),
            vec!["https://a.example", "https://b.example"]
        );

        let xml = "<urlset><url><loc>https://a.example/</loc></url>\
                   <url><loc>https://b.example/</loc></url></urlset>";
        assert_eq!(
            parse_sitemap_urls(xml),
            vec!["https://a.example/", "https://b.example/"]
        );
    }

    #[test]
    fn error_codes_are_classified() {
        assert_eq!(error_code("Invalid URL: nope"), "INVALID_TARGET");
        assert_eq!(
            error_code("robots.txt disallows crawling x"),
            "ROBOTS_DENIED"
        );
        assert_eq!(error_code("Failed to fetch URL: timeout"), "TIMEOUT");
        assert_eq!(
            error_code("Failed to fetch URL: dns error"),
            "NETWORK_ERROR"
        );
        assert_eq!(error_code("something odd"), "INTERNAL");
    }

    #[test]
    fn normalized_url_adds_scheme() {
        assert_eq!(normalize_url("example.com"), "https://example.com");
        assert_eq!(normalize_url(" http://example.com "), "http://example.com");
    }
}
