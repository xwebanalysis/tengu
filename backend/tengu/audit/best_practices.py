"""Best-practices / security checks."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..http import snippet, truncate
from ..models import Finding, Severity

SECURITY_HEADERS = [
    ("Strict-Transport-Security", Severity.WARNING,
     "Strict-Transport-Security: max-age=63072000; includeSubDomains; preload"),
    ("Content-Security-Policy", Severity.WARNING,
     "Content-Security-Policy: default-src 'self'; script-src 'self'"),
    ("X-Frame-Options", Severity.WARNING, "X-Frame-Options: DENY"),
    ("X-Content-Type-Options", Severity.WARNING, "X-Content-Type-Options: nosniff"),
    ("Referrer-Policy", Severity.INFO,
     "Referrer-Policy: strict-origin-when-cross-origin"),
    ("Permissions-Policy", Severity.INFO,
     "Permissions-Policy: camera=(), microphone=(), geolocation=()"),
]

DEPRECATED = {
    "center": "Use CSS Flexbox or Grid.",
    "font": "Use CSS font properties.",
    "marquee": "Use CSS animations or JavaScript.",
    "blink": "Use CSS animation; respect reduced-motion preferences.",
    "strike": "Use CSS text-decoration or the semantic <del> element.",
    "tt": "Use CSS monospace or semantic <code>/<kbd>/<samp>/<var>.",
    "big": "Use CSS font-size with relative units.",
    "frame": "Use <iframe> or a modern component architecture.",
    "frameset": "Framesets are obsolete; use <iframe> or server-side templates.",
    "noframes": "Framesets are obsolete; no replacement needed.",
    "applet": "Use <canvas>, WebGL or modern JavaScript.",
    "basefont": "Use CSS on :root or body.",
}


def analyze(html: str, headers, url: str) -> list[Finding]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Finding] = []
    https(url, out)
    security_headers(headers, out)
    csp(headers, out)
    permissions_policy(headers, out)
    cookies(headers, out)
    doctype(html, out)
    deprecated_html(soup, out)
    mixed_content(soup, out)
    sri(soup, out)
    gdpr_consent(soup, out)
    console_errors(out)
    return out


def https(url: str, out: list[Finding]) -> None:
    if url.startswith("http://"):
        out.append(Finding(
            "best_practices", "https", Severity.ERROR,
            "Page served over insecure HTTP",
            "Redirect all HTTP traffic to HTTPS, obtain a TLS certificate and enable HSTS. "
            "HTTP exposes cookies, credentials and content to interception.",
            url,
        ))


def security_headers(headers, out: list[Finding]) -> None:
    for name, severity, example in SECURITY_HEADERS:
        if headers.get(name) is None:
            out.append(Finding(
                "best_practices", "security_headers", severity,
                f"Missing {name} header",
                f"Add the {name} response header. Example:\n{example}",
                example,
            ))


def csp(headers, out: list[Finding]) -> None:
    value = headers.get("content-security-policy")
    if value is None:
        return
    directives = {
        part.strip().split(" ", 1)[0].lower()
        for part in value.split(";") if part.strip()
    }
    if not directives & {"default-src", "script-src", "style-src"}:
        out.append(Finding(
            "best_practices", "csp", Severity.WARNING,
            "CSP has no default-src, script-src or style-src",
            "The policy may be too permissive. Start with default-src 'self' and add "
            "only the sources you need.",
            truncate(value, 300),
        ))
    if "frame-ancestors" not in directives:
        out.append(Finding(
            "best_practices", "csp", Severity.INFO,
            "CSP is missing frame-ancestors",
            "Add frame-ancestors 'none' or 'self' to prevent clickjacking.",
            truncate(value, 300),
        ))
    if "unsafe-inline" in value and "script-src" in value:
        out.append(Finding(
            "best_practices", "csp", Severity.WARNING,
            "CSP allows unsafe-inline scripts",
            "unsafe-inline weakens XSS protection. Use nonces or hashes for inline scripts.",
            truncate(value, 300),
        ))


def permissions_policy(headers, out: list[Finding]) -> None:
    value = headers.get("permissions-policy") or headers.get("feature-policy")
    if value and "camera" not in value and "microphone" not in value and "geolocation" not in value:
        out.append(Finding(
            "best_practices", "permissions_policy", Severity.INFO,
            "Permissions-Policy does not restrict common device APIs",
            "Consider camera=(), microphone=(), geolocation=() unless the page needs them.",
            truncate(value, 300),
        ))


def cookies(headers, out: list[Finding]) -> None:
    values = headers.get_list("set-cookie") if hasattr(headers, "get_list") else []
    for value in values:
        lower = value.lower()
        name = value.split(";", 1)[0]
        if "secure" not in lower:
            out.append(Finding(
                "best_practices", "cookies", Severity.WARNING,
                f"Cookie \"{name}\" missing Secure flag",
                "Add ; Secure so the cookie is only sent over HTTPS.",
                truncate(value, 300),
            ))
        if "httponly" not in lower:
            out.append(Finding(
                "best_practices", "cookies", Severity.WARNING,
                f"Cookie \"{name}\" missing HttpOnly flag",
                "Add ; HttpOnly to keep the cookie out of document.cookie and reduce XSS impact.",
                truncate(value, 300),
            ))
        if "samesite" not in lower:
            out.append(Finding(
                "best_practices", "cookies", Severity.INFO,
                f"Cookie \"{name}\" missing SameSite attribute",
                "Add ; SameSite=Lax or SameSite=Strict to reduce CSRF risk.",
                truncate(value, 300),
            ))


def doctype(html: str, out: list[Finding]) -> None:
    if not html.lstrip().lower().startswith("<!doctype html"):
        out.append(Finding(
            "best_practices", "doctype", Severity.WARNING,
            "Missing or incorrect doctype declaration",
            "Add <!DOCTYPE html> as the first line to trigger standards mode.",
            truncate(html.lstrip(), 100),
        ))


def deprecated_html(soup: BeautifulSoup, out: list[Finding]) -> None:
    for tag, replacement in DEPRECATED.items():
        elements = soup.find_all(tag)
        if elements:
            out.append(Finding(
                "best_practices", "deprecated_html", Severity.WARNING,
                f"Deprecated <{tag}> element found ({len(elements)})",
                f"<{tag}> is obsolete in HTML5. {replacement}",
                snippet(elements[0]),
            ))


def mixed_content(soup: BeautifulSoup, out: list[Finding]) -> None:
    found: list[str] = []
    for selector, attr in (
        ("script[src]", "src"), ("link[href]", "href"),
        ("img[src]", "src"), ("iframe[src]", "src"),
    ):
        for element in soup.select(selector):
            value = element.get(attr) or ""
            if value.startswith("http://"):
                found.append(value)
    if found:
        out.append(Finding(
            "best_practices", "mixed_content", Severity.ERROR,
            f"Mixed content detected — {len(found)} HTTP resource(s)",
            "Replace all http:// resources with https:// equivalents; otherwise browsers "
            "may block them or warn users. Examples:\n" +
            "\n".join("  · " + truncate(item, 120) for item in found[:5]),
            truncate(found[0], 300),
        ))


def sri(soup: BeautifulSoup, out: list[Finding]) -> None:
    resources = soup.select("script[src]:not([integrity]), link[rel=stylesheet][href]:not([integrity])")
    if resources:
        out.append(Finding(
            "best_practices", "sri", Severity.INFO,
            f"{len(resources)} external resource(s) missing Subresource Integrity",
            "Add integrity=\"sha384-...\" and crossorigin=\"anonymous\" to third-party "
            "scripts and stylesheets so a compromised CDN cannot inject code.",
            snippet(resources[0]),
        ))


def gdpr_consent(soup: BeautifulSoup, out: list[Finding]) -> None:
    text = soup.get_text(" ", strip=True).lower()
    markers = ("cookie", "cookies", "consent", "gdpr", "privacy")
    if any(marker in text for marker in markers):
        out.append(Finding(
            "best_practices", "gdpr_consent", Severity.INFO,
            "Cookie/consent language detected",
            "Verify that consent is opt-in, granular and that non-essential cookies are "
            "blocked until the user agrees.",
        ))


def console_errors(out: list[Finding]) -> None:
    out.append(Finding(
        "best_practices", "console_errors", Severity.INFO,
        "Console errors require a browser runtime",
        "Static HTML cannot detect JavaScript exceptions, failed network requests or "
        "CSP violations. Use a headless browser for runtime console capture.",
    ))
