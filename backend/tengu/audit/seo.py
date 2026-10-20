"""SEO checks, including network-level robots/sitemap/link checks."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..config import Config
from ..http import (
    FetchError,
    HttpClient,
    extract_links,
    parse_sitemap_urls,
    snippet,
    truncate,
)
from ..models import Finding, Severity

REQUIRED_OG = ["og:title", "og:type", "og:image", "og:url", "og:description"]
REQUIRED_TW = ["twitter:card", "twitter:title", "twitter:description", "twitter:image"]


def analyze(html: str, page_url: str) -> list[Finding]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Finding] = []
    title(soup, out)
    meta_description(soup, out)
    headings(soup, out)
    canonical(soup, page_url, out)
    open_graph(soup, out)
    twitter_card(soup, out)
    json_ld(soup, out)
    meta_robots(soup, out)
    hreflang(soup, out)
    lang(soup, out)
    microdata(soup, out)
    return out


async def analyze_network(
    client: HttpClient, page_url: str, html: str, cfg: Config
) -> list[Finding]:
    out: list[Finding] = []
    origin = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    sitemaps: list[str] = []
    try:
        robots = await client.fetch_text(f"{origin}/robots.txt", timeout=5)
        sitemaps = robots_txt(robots, out)
    except FetchError:
        out.append(Finding(
            "seo", "robots_txt", Severity.INFO,
            "No robots.txt found or it is unreachable",
            "A robots.txt is optional, but it helps crawlers discover sitemaps and "
            "control indexing. Add one at the site root if the site is public.",
        ))
    sitemap_url = sitemaps[0] if sitemaps else f"{origin}/sitemap.xml"
    try:
        xml = await client.fetch_text(sitemap_url, timeout=5)
        sitemap(xml, sitemap_url, out)
    except FetchError:
        out.append(Finding(
            "seo", "sitemap", Severity.INFO,
            "No sitemap.xml found or it is unreachable",
            "Add an XML sitemap and reference it from robots.txt so search engines "
            "can discover all indexable URLs.",
        ))
    await broken_links(client, page_url, html, out)
    await redirect_chain(client, page_url, out)
    return out


def title(soup: BeautifulSoup, out: list[Finding]) -> None:
    tag = soup.select_one("head > title")
    if tag is None:
        out.append(Finding("seo", "title", Severity.ERROR, "Missing title tag",
                           "Add a descriptive <title> of 50–60 characters with the primary "
                           "keyword near the front."))
        return
    text = tag.get_text(strip=True)
    length = len(text)
    if not text:
        out.append(Finding("seo", "title", Severity.ERROR, "Empty title tag",
                           "The <title> exists but has no text. Add a descriptive title.",
                           snippet(tag)))
    elif length < 30:
        out.append(Finding("seo", "title", Severity.WARNING, "Title too short",
                           f"Title has {length} characters; aim for 50–60. Current: \"{truncate(text, 100)}\"",
                           snippet(tag)))
    elif length > 60:
        out.append(Finding("seo", "title", Severity.WARNING, "Title too long",
                           f"Title has {length} characters; search results truncate around 60.",
                           snippet(tag)))


def meta_description(soup: BeautifulSoup, out: list[Finding]) -> None:
    tag = soup.find("meta", attrs={"name": re.compile("^description$", re.IGNORECASE)})
    if tag is None:
        out.append(Finding("seo", "meta_description", Severity.WARNING,
                           "Missing meta description",
                           "Add a 50–160 character summary to improve click-through rate."))
        return
    content = (tag.get("content") or "").strip()
    length = len(content)
    if not content:
        out.append(Finding("seo", "meta_description", Severity.WARNING,
                           "Empty meta description",
                           "The tag exists but has no content.", snippet(tag)))
    elif length < 50:
        out.append(Finding("seo", "meta_description", Severity.WARNING,
                           "Meta description too short",
                           f"Description has {length} characters; aim for 50–160.",
                           snippet(tag)))
    elif length > 160:
        out.append(Finding("seo", "meta_description", Severity.WARNING,
                           "Meta description too long",
                           f"Description has {length} characters; search engines truncate around 160.",
                           snippet(tag)))


def headings(soup: BeautifulSoup, out: list[Finding]) -> None:
    tags = soup.find_all(re.compile(r"^h[1-6]$"))
    if not tags:
        out.append(Finding("seo", "headings", Severity.ERROR, "No headings found",
                           "Add an h1 for the primary topic and h2/h3 for sections."))
        return
    h1s = [tag for tag in tags if tag.name == "h1"]
    if not h1s:
        out.append(Finding("seo", "headings", Severity.ERROR, "Missing h1 heading",
                           "Every page should have exactly one h1 describing its main topic.",
                           snippet(tags[0])))
    elif len(h1s) > 1:
        out.append(Finding("seo", "headings", Severity.WARNING, "Multiple h1 headings",
                           f"Found {len(h1s)} h1 elements. Keep one and demote the rest.",
                           snippet(h1s[0])))


def canonical(soup: BeautifulSoup, page_url: str, out: list[Finding]) -> None:
    tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    if tag is None:
        out.append(Finding("seo", "canonical", Severity.INFO, "No canonical URL",
                           f"Add <link rel=\"canonical\" href=\"{page_url}\"> if the content "
                           "is reachable through multiple URLs."))
        return
    href = (tag.get("href") or "").strip()
    if not href:
        out.append(Finding("seo", "canonical", Severity.ERROR, "Empty canonical URL",
                           "Set the href to the preferred canonical URL.", snippet(tag)))
        return
    canonical_host = urlparse(href).hostname or ""
    page_host = urlparse(page_url).hostname or ""
    if canonical_host and canonical_host != page_host:
        out.append(Finding("seo", "canonical", Severity.WARNING,
                           "Cross-domain canonical URL",
                           f"Canonical points to {canonical_host}, not {page_host}. "
                           "Only use this intentionally for syndicated content.",
                           snippet(tag)))
    elif urlparse(href).path != urlparse(page_url).path:
        out.append(Finding("seo", "canonical", Severity.INFO,
                           "Canonical URL differs from page URL",
                           f"Canonical: {href}\nPage: {page_url}", snippet(tag)))


def open_graph(soup: BeautifulSoup, out: list[Finding]) -> None:
    tags = soup.find_all("meta", attrs={"property": re.compile(r"^og:", re.IGNORECASE)})
    present = {tag.get("property", "").lower(): tag for tag in tags}
    if not tags:
        out.append(Finding("seo", "open_graph", Severity.WARNING, "No Open Graph tags",
                           "Add og:title, og:type, og:image, og:url and og:description "
                           "to control how links appear on social platforms."))
        return
    for prop in REQUIRED_OG:
        tag = present.get(prop)
        if tag is None:
            out.append(Finding("seo", "open_graph",
                               Severity.INFO if prop == "og:image" else Severity.WARNING,
                               f"Missing {prop}", f"Add <meta property=\"{prop}\" content=\"...\">."))
        else:
            out.append(Finding("seo", "open_graph", Severity.PASS, f"{prop} is present",
                               f"Content: \"{truncate(tag.get('content', ''), 100)}\"",
                               snippet(tag)))


def twitter_card(soup: BeautifulSoup, out: list[Finding]) -> None:
    tags = soup.find_all("meta", attrs={"name": re.compile(r"^twitter:", re.IGNORECASE)})
    present = {tag.get("name", "").lower(): tag for tag in tags}
    if not tags:
        out.append(Finding("seo", "twitter_card", Severity.INFO, "No Twitter Card tags",
                           "Add twitter:card, twitter:title, twitter:description and "
                           "twitter:image, or rely on Open Graph fallbacks."))
        return
    for prop in REQUIRED_TW:
        tag = present.get(prop)
        if tag is None:
            out.append(Finding("seo", "twitter_card", Severity.INFO, f"Missing {prop}",
                               f"Add <meta name=\"{prop}\" content=\"...\">."))
        else:
            out.append(Finding("seo", "twitter_card", Severity.PASS, f"{prop} is present",
                               f"Content: \"{truncate(tag.get('content', ''), 100)}\"",
                               snippet(tag)))


def json_ld(soup: BeautifulSoup, out: list[Finding]) -> None:
    blocks = soup.find_all("script", attrs={"type": re.compile("application/ld\\+json", re.IGNORECASE)})
    if not blocks:
        out.append(Finding("seo", "json_ld", Severity.INFO, "No JSON-LD structured data",
                           "Add Schema.org JSON-LD to help search engines understand the page."))
        return
    valid = 0
    for block in blocks:
        try:
            json.loads(block.string or block.get_text())
            valid += 1
        except (ValueError, TypeError):
            out.append(Finding("seo", "json_ld", Severity.WARNING,
                               "Invalid JSON-LD block",
                               "The JSON-LD script could not be parsed as JSON.",
                               snippet(block)))
    if valid:
        out.append(Finding("seo", "json_ld", Severity.PASS,
                           f"{valid} valid JSON-LD block(s) found",
                           "Structured data is present and parseable."))


def meta_robots(soup: BeautifulSoup, out: list[Finding]) -> None:
    tag = soup.find("meta", attrs={"name": re.compile("^robots$", re.IGNORECASE)})
    if tag is None:
        return
    content = (tag.get("content") or "").lower()
    if "noindex" in content:
        out.append(Finding("seo", "meta_robots", Severity.WARNING,
                           "Page is marked noindex",
                           "meta robots contains noindex; the page will not appear in search results.",
                           snippet(tag)))
    elif "nofollow" in content:
        out.append(Finding("seo", "meta_robots", Severity.INFO,
                           "Page is marked nofollow",
                           "Links on this page will not be followed by search engines.",
                           snippet(tag)))


def hreflang(soup: BeautifulSoup, out: list[Finding]) -> None:
    tags = soup.find_all("link", attrs={"rel": re.compile("alternate", re.IGNORECASE), "hreflang": True})
    if not tags:
        return
    langs = [tag.get("hreflang") for tag in tags]
    if "x-default" not in langs:
        out.append(Finding("seo", "hreflang", Severity.INFO,
                           "hreflang is missing x-default",
                           "Add an x-default alternate for users whose language is not listed."))
    out.append(Finding("seo", "hreflang", Severity.PASS,
                       f"{len(tags)} hreflang alternate(s) found",
                       "Languages: " + ", ".join(str(lang) for lang in langs[:10])))


def lang(soup: BeautifulSoup, out: list[Finding]) -> None:
    html_tag = soup.find("html")
    if html_tag is None:
        return
    lang_value = (html_tag.get("lang") or "").strip()
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", lang_value):
        out.append(Finding("seo", "lang_attribute", Severity.WARNING,
                           "Missing or invalid html lang attribute",
                           "Use a valid BCP 47 language code such as en, es or en-US.",
                           snippet(html_tag)))


def microdata(soup: BeautifulSoup, out: list[Finding]) -> None:
    items = soup.select("[itemscope]")
    rdf = soup.select("[typeof], [property]")
    if items or rdf:
        out.append(Finding("seo", "structured_data_microdata", Severity.INFO,
                           f"Microdata/RDFa detected ({len(items)} itemscope, {len(rdf)} properties)",
                           "Microdata/RDFa is present. JSON-LD is generally easier to maintain."))
    else:
        out.append(Finding("seo", "structured_data_microdata", Severity.INFO,
                           "No Microdata or RDFa detected",
                           "JSON-LD is preferred, but Microdata/RDFa are valid alternatives."))


def robots_txt(text: str, out: list[Finding]) -> list[str]:
    sitemaps = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", text)
    disallow_all = re.search(r"(?im)^\s*user-agent\s*:\s*\*\s*$[\s\S]{0,200}?^\s*disallow\s*:\s*/\s*$", text)
    if disallow_all:
        out.append(Finding("seo", "robots_txt", Severity.ERROR,
                           "robots.txt blocks all crawlers",
                           "A 'Disallow: /' rule for User-agent: * prevents search engines "
                           "from indexing the site."))
    else:
        out.append(Finding("seo", "robots_txt", Severity.PASS,
                           "robots.txt found and does not block all crawlers",
                           f"Sitemap references: {len(sitemaps)}"))
    return sitemaps


def sitemap(xml: str, url: str, out: list[Finding]) -> None:
    urls = parse_sitemap_urls(xml)
    if not urls:
        out.append(Finding("seo", "sitemap", Severity.WARNING, "Sitemap contains no URLs",
                           f"The sitemap at {url} has no <loc> entries."))
        return
    out.append(Finding("seo", "sitemap", Severity.PASS,
                       f"Sitemap found with {len(urls)} URL(s)",
                       f"Sitemap: {url}"))


async def broken_links(client: HttpClient, page_url: str, html: str, out: list[Finding]) -> None:
    links = extract_links(html, page_url)
    broken: list[str] = []
    checked = 0
    for link in links:
        if checked >= 10:
            break
        checked += 1
        try:
            result = await client.fetch(link, timeout=5)
        except FetchError:
            continue
        if result.status_code in (404, 410):
            broken.append(f"{result.status_code} {link}")
    if broken:
        out.append(Finding("seo", "broken_links", Severity.WARNING,
                           f"{len(broken)} broken link(s) detected",
                           "Remove or fix links returning 404/410:\n" + "\n".join(broken)))


async def redirect_chain(client: HttpClient, page_url: str, out: list[Finding]) -> None:
    try:
        result = await client.fetch(page_url, timeout=10)
    except FetchError:
        return
    if result.final_url.rstrip("/") != page_url.rstrip("/"):
        out.append(Finding("seo", "redirect_chain", Severity.INFO,
                           "URL redirects to a different final URL",
                           f"{page_url} → {result.final_url}. Use a direct canonical URL "
                           "to avoid unnecessary redirects."))
