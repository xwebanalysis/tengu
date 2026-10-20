"""HTTP fetching, retries, URL helpers and batch/crawl discovery."""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .config import Config


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: httpx.Headers
    text: str
    content_type: str

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower() or self.content_type == ""


class HttpClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=cfg.http_max_redirects,
            timeout=httpx.Timeout(cfg.timeout),
            headers={"User-Agent": cfg.http_user_agent},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str, *, timeout: float | None = None) -> FetchResult:
        last_error: str | None = None
        attempts = self.cfg.http_retry_count + 1
        for attempt in range(attempts):
            try:
                response = await self._client.get(
                    url, timeout=timeout or self.cfg.timeout
                )
                text = response.text
                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers=response.headers,
                    text=text,
                    content_type=response.headers.get("content-type", ""),
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                if attempt >= attempts - 1:
                    break
                base = min(5000, 250 * (2 ** min(attempt, 4)))
                await asyncio.sleep((base + random.randint(0, base // 2)) / 1000)
        raise FetchError(f"Failed to fetch {url} after {attempts} attempt(s): {last_error}")

    async def fetch_text(self, url: str, *, timeout: float = 5.0) -> str:
        result = await self.fetch(url, timeout=timeout)
        if result.status_code >= 400:
            raise FetchError(f"HTTP {result.status_code}")
        return result.text


def normalize_url(url: str) -> str:
    value = url.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return "https://" + value


def base_origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def is_crawlable_link(base_url: str, href: str, include_subdomains: bool) -> str | None:
    try:
        absolute = urljoin(base_url, href)
    except ValueError:
        return None
    parsed = urlparse(absolute)
    base = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return None
    base_host = base.hostname or ""
    host = parsed.hostname or ""
    if include_subdomains:
        bare = base_host.removeprefix("www.")
        same = host == base_host or host.endswith(f".{base_host}") or host.endswith(f".{bare}")
        if not same:
            return None
    elif host != base_host:
        return None
    return strip_fragment(absolute)


def parse_sitemap_urls(xml: str) -> list[str]:
    soup = BeautifulSoup(xml, "xml")
    urls: list[str] = []
    for loc in soup.find_all("loc"):
        value = loc.get_text(strip=True)
        if value and value not in urls:
            urls.append(value)
    return urls


def parse_csv_urls(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        first = value.split(",")[0].strip()
        if first.startswith(("http://", "https://")) and first not in urls:
            urls.append(first)
    return urls


def parse_robots_txt(text: str, user_agent: str) -> RobotsRules:
    ua_lower = user_agent.lower()
    groups: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if not last_was_agent or current is None:
                if current is not None:
                    groups.append(current)
                current = {"agents": [], "allow": [], "disallow": [], "crawl_delay": None}
            assert current is not None
            current["agents"].append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if current is not None:
                current[key].append(value)
            last_was_agent = False
        elif key == "crawl-delay":
            if current is not None:
                try:
                    current["crawl_delay"] = int(float(value))
                except ValueError:
                    pass
            last_was_agent = False
        else:
            last_was_agent = False
    if current is not None:
        groups.append(current)

    specific = next(
        (
            g
            for g in groups
            if any(a != "*" and a in ua_lower for a in g["agents"])
        ),
        None,
    )
    selected = [specific] if specific else [g for g in groups if "*" in g["agents"]]
    rules = RobotsRules()
    for group in selected:
        rules.allow.extend(group["allow"])
        rules.disallow.extend(group["disallow"])
        if rules.crawl_delay is None:
            rules.crawl_delay = group["crawl_delay"]
    return rules


@dataclass
class RobotsRules:
    allow: list[str] = None  # type: ignore[assignment]
    disallow: list[str] = None  # type: ignore[assignment]
    crawl_delay: int | None = None

    def __post_init__(self) -> None:
        if self.allow is None:
            self.allow = []
        if self.disallow is None:
            self.disallow = []


def _robots_pattern_matches(pattern: str, path: str) -> bool:
    if not pattern:
        return False
    anchored_end = pattern.endswith("$")
    pattern = pattern.rstrip("$")
    parts = pattern.split("*")
    if len(parts) == 1:
        return path == pattern if anchored_end else path.startswith(pattern)
    if not path.startswith(parts[0]):
        return False
    pos = len(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        last = index == len(parts) - 1
        if not part:
            if last and anchored_end:
                return True
            continue
        if last and anchored_end:
            return path[pos:].endswith(part)
        found = path.find(part, pos)
        if found < 0:
            return False
        pos = found + len(part)
    return True


def robots_allows(rules: RobotsRules, path: str) -> bool:
    decision: tuple[int, bool] | None = None
    for pattern in rules.disallow:
        if _robots_pattern_matches(pattern, path):
            length = len(pattern)
            if decision is None or length > decision[0]:
                decision = (length, False)
    for pattern in rules.allow:
        if _robots_pattern_matches(pattern, path):
            length = len(pattern)
            if decision is None or length >= decision[0]:
                decision = (length, True)
    return decision[1] if decision else True


async def fetch_batch_urls(client: HttpClient, batch_url: str, fmt: str) -> list[str]:
    result = await client.fetch(batch_url)
    body = result.text
    if fmt == "csv" or batch_url.endswith(".csv"):
        urls = parse_csv_urls(body)
    else:
        urls = parse_sitemap_urls(body)
        if not urls:
            urls = parse_csv_urls(body)
        if not urls:
            urls = [
                line.strip()
                for line in body.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
    if not urls:
        raise FetchError("No URLs found in batch source")
    return urls


async def crawl_site(
    client: HttpClient,
    entry_url: str,
    include_subdomains: bool,
    cfg: Config,
    on_page,
    on_progress,
) -> list[str]:
    base_url = entry_url
    discovered: list[str] = []
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(entry_url, 0)])
    robots_cache: dict[str, RobotsRules] = {}

    while queue:
        if len(discovered) >= cfg.max_crawl_pages:
            await on_progress(f"Page limit reached (TENGU_MAX_PAGES={cfg.max_crawl_pages})")
            break
        current, depth = queue.popleft()
        if current in visited:
            continue
        parsed = urlparse(current)
        if cfg.crawl_respect_robots:
            origin = base_origin(current)
            rules = robots_cache.get(origin)
            if rules is None:
                robots_url = f"{origin}/robots.txt"
                try:
                    result = await client.fetch(robots_url)
                    if result.status_code == 404:
                        rules = RobotsRules()
                    elif result.status_code in (401, 403):
                        rules = RobotsRules(disallow=["/"])
                    else:
                        rules = parse_robots_txt(result.text, cfg.http_user_agent)
                except FetchError:
                    rules = RobotsRules()
                robots_cache[origin] = rules
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            if not robots_allows(rules, path):
                if not discovered:
                    raise FetchError(f"robots.txt disallows crawling {current}")
                await on_progress(f"Skipping {current} (robots.txt)")
                continue

        visited.add(current)
        if discovered:
            delay = random.randint(cfg.crawl_delay_min_ms, cfg.crawl_delay_max_ms) / 1000
            await asyncio.sleep(delay)
        discovered.append(current)
        await on_page(current)

        if depth >= cfg.crawl_depth:
            continue
        try:
            result = await client.fetch(current)
        except FetchError as exc:
            await on_progress(f"Failed to fetch {current}: {exc}")
            continue
        if not result.is_html:
            continue
        soup = BeautifulSoup(result.text, "lxml")
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not href:
                continue
            candidate = is_crawlable_link(base_url, href, include_subdomains)
            if not candidate:
                continue
            if candidate in visited or any(item[0] == candidate for item in queue):
                continue
            if len(discovered) + len(queue) < cfg.max_crawl_pages:
                queue.append((candidate, depth + 1))
    return discovered


def extract_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in ("http", "https") and absolute not in links:
            links.append(absolute)
    return links


def truncate(value: str, size: int) -> str:
    return value if len(value) <= size else value[: max(0, size - 1)] + "…"


def snippet(element, limit: int = 300) -> str | None:
    if element is None:
        return None
    html = str(element)
    if not html:
        return None
    return truncate(html, limit)
