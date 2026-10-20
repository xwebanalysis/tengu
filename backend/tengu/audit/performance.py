"""Performance checks."""

from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..http import snippet, truncate
from ..models import Finding, Severity


def analyze(html: str, headers, page_url: str = "") -> list[Finding]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Finding] = []
    page_weight(html, out)
    resources(soup, out)
    images(soup, out)
    fonts(soup, out)
    cache(headers, out)
    compression(headers, out)
    render_blocking(soup, out)
    third_party(soup, out, page_url)
    web_vitals(out)
    return out


def page_weight(html: str, out: list[Finding]) -> None:
    size = len(html.encode("utf-8"))
    kb = size / 1024
    if kb > 2000:
        severity, note = Severity.ERROR, "exceeds the 2 MB recommended maximum"
    elif kb > 500:
        severity, note = Severity.WARNING, "is between 500 KB and 2 MB"
    elif kb > 100:
        severity, note = Severity.INFO, "is between 100 KB and 500 KB"
    else:
        severity, note = Severity.PASS, "is under 100 KB"
    out.append(Finding(
        "performance", "page_weight", severity,
        f"HTML document size: {kb:.1f} KB ({kb / 1024:.2f} MB)",
        f"The raw HTML document is {kb:.1f} KB ({size} bytes) and {note}. "
        "Target under 100 KB, remove unused markup, stream HTML and cache at the edge.",
        truncate(html, 300),
    ))


def resources(soup: BeautifulSoup, out: list[Finding]) -> None:
    css = len(soup.select("link[rel=stylesheet]"))
    js = len(soup.select("script[src]"))
    images = len(soup.select("img[src], source[src]"))
    iframes = len(soup.select("iframe[src]"))
    hints = len(soup.select("link[rel=preload], link[rel=prefetch]"))
    total = css + js + images + iframes + hints
    if total < 10:
        return
    if total > 100:
        severity = Severity.ERROR
    elif total > 50:
        severity = Severity.WARNING
    else:
        severity = Severity.INFO
    out.append(Finding(
        "performance", "resource_waterfall", severity,
        f"{total} external resource(s) — {css} CSS, {js} JS, {images} images, "
        f"{iframes} iframes, {hints} prefetch/preload",
        "Reduce request count by bundling, using HTTP/2 or HTTP/3, lazy-loading "
        "below-fold assets and removing unused CSS/JS.",
        snippet(soup.select_one("link[rel=stylesheet], script[src]")),
    ))


def images(soup: BeautifulSoup, out: list[Finding]) -> None:
    images = [img for img in soup.find_all("img") if not (img.get("src") or "").startswith("data:")]
    if not images:
        return
    no_dimensions = [
        img for img in images if img.get("width") is None and img.get("height") is None
    ]
    no_lazy = [img for img in images if img.get("loading") is None]
    if no_dimensions:
        examples = "\n".join(
            f"  · <img src=\"{truncate(img.get('src', ''), 100)}\">" for img in no_dimensions[:3]
        )
        out.append(Finding(
            "performance", "image_optimization",
            Severity.ERROR if len(no_dimensions) == len(images) else Severity.WARNING,
            f"{len(no_dimensions)}/{len(images)} image(s) missing explicit width and height",
            "Without intrinsic dimensions the browser cannot reserve space, causing "
            "Cumulative Layout Shift. Add width and height or CSS aspect-ratio.\n\n" + examples,
            snippet(no_dimensions[0]),
        ))
    if no_lazy:
        out.append(Finding(
            "performance", "image_optimization", Severity.INFO,
            f"{len(no_lazy)}/{len(images)} image(s) without loading=\"lazy\"",
            "Add loading=\"lazy\" to below-the-fold images. Do not lazy-load the LCP image.",
            snippet(no_lazy[0]),
        ))


def fonts(soup: BeautifulSoup, out: list[Finding]) -> None:
    google = soup.select_one("link[href*='fonts.googleapis.com']")
    has_font_face = any("@font-face" in tag.get_text() for tag in soup.find_all("style"))
    has_preconnect = soup.select_one(
        "link[rel=preconnect][href*='fonts.googleapis.com'],"
        "link[rel=preconnect][href*='fonts.gstatic.com']"
    )
    has_preload = soup.select_one("link[rel=preload][as=font]")
    if google is not None:
        if has_preconnect is None:
            out.append(Finding(
                "performance", "font_loading", Severity.WARNING,
                "Google Fonts loaded without preconnect hints",
                "Add preconnect hints for fonts.googleapis.com and fonts.gstatic.com "
                "to avoid an extra DNS/TCP/TLS round trip.",
                snippet(google),
            ))
        if has_preload is None:
            out.append(Finding(
                "performance", "font_loading", Severity.INFO,
                "Google Fonts without font file preload",
                "Preload only the critical above-the-fold font files with "
                "<link rel=\"preload\" as=\"font\" crossorigin>.",
                snippet(google),
            ))
    if has_font_face and not soup.select_one("link[rel=preconnect]"):
        style = next(tag for tag in soup.find_all("style") if "@font-face" in tag.get_text())
        out.append(Finding(
            "performance", "font_loading", Severity.INFO,
            "@font-face used without preconnect to font origins",
            "Add preconnect hints if fonts are hosted on another origin.",
            snippet(style),
        ))
    if google is None and not has_font_face:
        styled = soup.select_one("[style*='font-family']")
        if styled is not None:
            out.append(Finding(
                "performance", "font_loading", Severity.PASS,
                "No web fonts detected — system fonts in use",
                "The page relies on system fonts, avoiding font download and FOIT/FOUT.",
            ))


def cache(headers, out: list[Finding]) -> None:
    cache_control = headers.get("cache-control")
    etag = headers.get("etag")
    last_modified = headers.get("last-modified")
    expires = headers.get("expires")
    if cache_control is None:
        out.append(Finding(
            "performance", "cache_policy", Severity.WARNING,
            "Missing Cache-Control header",
            "Set an explicit policy: public, max-age=31536000, immutable for hashed "
            "assets; no-cache for HTML; no-store for sensitive API responses.",
            "Cache-Control: <missing>",
        ))
    else:
        lower = cache_control.lower()
        if not any(token in lower for token in ("max-age", "s-maxage", "no-cache", "no-store")):
            out.append(Finding(
                "performance", "cache_policy", Severity.INFO,
                "Cache-Control header present but no caching directive",
                f"Cache-Control is \"{cache_control}\" but lacks max-age, s-maxage, "
                "no-cache or no-store.",
                f"Cache-Control: {cache_control}",
            ))
    if etag is None and last_modified is None:
        out.append(Finding(
            "performance", "cache_policy", Severity.INFO,
            "No conditional request headers (ETag or Last-Modified)",
            "Add ETag or Last-Modified so browsers can use conditional requests and 304 responses.",
            "ETag: \"<file-hash>\"\nLast-Modified: <HTTP-date>",
        ))
    if expires is not None:
        out.append(Finding(
            "performance", "cache_policy", Severity.INFO,
            "Legacy Expires header should be replaced by Cache-Control max-age",
            "Expires depends on clock synchronization; Cache-Control max-age is relative "
            "and preferred in HTTP/1.1.",
            f"Expires: {expires}",
        ))


def compression(headers, out: list[Finding]) -> None:
    encoding = headers.get("content-encoding")
    if encoding is None:
        out.append(Finding(
            "performance", "compression", Severity.WARNING,
            "Response is not compressed",
            "Enable Brotli (preferred) or gzip for HTML, CSS, JavaScript and JSON. "
            "Add Vary: Accept-Encoding.",
            "Content-Encoding: <missing>",
        ))
        return
    value = encoding.lower()
    if value == "br":
        out.append(Finding(
            "performance", "compression", Severity.PASS,
            "Content compressed with Brotli (br)",
            "Brotli is the most efficient compression method for web text content.",
            "Content-Encoding: br",
        ))
    elif value == "gzip":
        out.append(Finding(
            "performance", "compression", Severity.PASS,
            "Content compressed with Gzip",
            "Gzip is widely supported; consider Brotli for 20–30% better compression.",
            "Content-Encoding: gzip",
        ))
    else:
        out.append(Finding(
            "performance", "compression", Severity.WARNING,
            "Unknown or uncommon content encoding",
            f"Content-Encoding: {encoding} is not one of the standard web methods "
            "(br, gzip, deflate).",
            f"Content-Encoding: {encoding}",
        ))


def render_blocking(soup: BeautifulSoup, out: list[Finding]) -> None:
    blocking_scripts = [
        script for script in soup.select("script[src]")
        if script.get("async") is None
        and script.get("defer") is None
        and script.get("type") != "module"
    ]
    blocking_css = soup.select("link[rel=stylesheet]:not([media=print]):not([disabled])")
    total = len(blocking_scripts) + len(blocking_css)
    if total == 0:
        return
    examples = [snippet(item) for item in (blocking_scripts + blocking_css)[:5] if snippet(item)]
    out.append(Finding(
        "performance", "render_blocking", Severity.WARNING if total > 3 else Severity.INFO,
        f"{total} render-blocking resource(s) in <head>",
        "Add defer/async to scripts and inline or preload critical CSS. "
        "Render-blocking resources delay First Contentful Paint.",
        "\n".join(examples) if examples else None,
    ))


def third_party(soup: BeautifulSoup, out: list[Finding], page_url: str) -> None:
    page_host = urlparse(page_url).hostname or ""
    external = []
    for script in soup.select("script[src]"):
        src = script.get("src") or ""
        parsed = urlparse(src)
        if parsed.netloc and page_host and parsed.netloc != page_host:
            external.append(script)
    if not external:
        return
    out.append(Finding(
        "performance", "third_party_scripts",
        Severity.WARNING if len(external) > 5 else Severity.INFO,
        f"{len(external)} third-party script(s) detected",
        "Third-party scripts compete for bandwidth and CPU. Audit them, load them "
        "asynchronously, self-host critical ones and remove unused vendors.",
        "\n".join(filter(None, (snippet(item) for item in external[:5]))),
    ))


def web_vitals(out: list[Finding]) -> None:
    out.append(Finding(
        "performance", "web_vitals", Severity.INFO,
        "Core Web Vitals require a browser runtime",
        "LCP, CLS and INP cannot be measured from static HTML. Use a headless browser "
        "or Chrome UX Report for field data.",
    ))
