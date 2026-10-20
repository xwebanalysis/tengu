"""Environment configuration and per-request audit options."""

from __future__ import annotations

import os
from dataclasses import dataclass

VERSION = "0.2.0"
ALL_CHECKS = "performance,seo,accessibility,best_practices"


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else None


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


@dataclass(slots=True)
class Config:
    port: int = 8070
    static_dir: str = "static/browser"
    max_history: int = 100
    api_key: str | None = None
    http_timeout_secs: int = 30
    http_max_redirects: int = 10
    http_retry_count: int = 2
    http_user_agent: str = ""
    rate_limit_per_minute: float = 120.0
    rate_limit_burst: int = 30
    max_concurrent_audits: int = 3
    database_url: str | None = None
    db_path: str = "tengu.db"
    cors_origins: list[str] | None = None
    crawl_delay_min_ms: int = 200
    crawl_delay_max_ms: int = 800
    max_crawl_pages: int = 50
    crawl_depth: int = 2
    crawl_respect_robots: bool = True

    @classmethod
    def from_env(cls) -> Config:
        min_delay = _int("TENGU_CRAWL_DELAY_MIN_MS", 200)
        max_delay = _int("TENGU_CRAWL_DELAY_MAX_MS", 800)
        min_delay = min(min_delay, max_delay)
        rate = _float("TENGU_RATE_LIMIT_PER_MINUTE", 0.0)
        if rate <= 0:
            rate = _float("TENGU_RATE_LIMIT_PER_SECOND", 0.0) * 60.0
        if rate <= 0:
            rate = 120.0
        raw_origins = _env("XWA_CORS_ORIGINS")
        origins = [o.strip() for o in raw_origins.split(",") if o.strip()] if raw_origins else []
        return cls(
            port=_int("PORT", 8070),
            static_dir=_env("STATIC_DIR") or "static/browser",
            max_history=max(1, _int("TENGU_MAX_HISTORY", 100)),
            api_key=_env("TENGU_API_KEY"),
            http_timeout_secs=max(1, _int("TENGU_HTTP_TIMEOUT", 30)),
            http_max_redirects=max(0, _int("TENGU_HTTP_MAX_REDIRECTS", 10)),
            http_retry_count=max(0, _int("TENGU_HTTP_RETRY", 2)),
            http_user_agent=_env("TENGU_USER_AGENT")
            or f"Tengu/{VERSION} (+https://github.com/xwebanalysis/tengu)",
            rate_limit_per_minute=max(1.0, rate),
            rate_limit_burst=max(1, _int("TENGU_RATE_LIMIT_BURST", 30)),
            max_concurrent_audits=max(1, _int("TENGU_MAX_CONCURRENT", 3)),
            database_url=_env("DATABASE_URL"),
            db_path=_env("TENGU_DB_PATH") or "tengu.db",
            cors_origins=origins,
            crawl_delay_min_ms=max(0, min_delay),
            crawl_delay_max_ms=max(0, max_delay),
            max_crawl_pages=max(1, _int("TENGU_MAX_PAGES", 50)),
            crawl_depth=max(0, _int("TENGU_CRAWL_DEPTH", 2)),
            crawl_respect_robots=(_env("TENGU_ROBOTS_TXT") or "1") not in ("0", "false", "False"),
        )

    @property
    def timeout(self) -> float:
        return float(max(1, self.http_timeout_secs))


@dataclass(slots=True)
class AuditOptions:
    url: str
    mode: str = ""
    subdomains: bool = False
    checks: str = ALL_CHECKS
    batch_url: str = ""
    batch_format: str = ""

    def has_check(self, name: str) -> bool:
        return name in {part.strip() for part in self.checks.split(",") if part.strip()}

    def is_full_site(self) -> bool:
        return self.mode == "fullsite"

    def is_batch(self) -> bool:
        return self.mode == "batch"


def normalize_url(url: str) -> str:
    value = url.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return "https://" + value
