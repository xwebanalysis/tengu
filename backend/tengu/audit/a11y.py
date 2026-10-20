"""Accessibility checks (static HTML, WCAG-oriented)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..http import snippet, truncate
from ..models import Finding, Severity

GENERIC_LINKS = {
    "click here", "here", "read more", "more", "learn more", "this", "link",
    "go", "details", "info", "continue", "start",
}

TEXT_TAGS = (
    "p", "span", "div", "h1", "h2", "h3", "h4", "h5", "h6", "a", "li",
    "td", "th", "label", "legend", "blockquote", "figcaption", "cite",
    "small", "strong", "em", "b", "i", "u", "code", "pre",
)

NAMED_COLORS = {
    "black": (0, 0, 0), "silver": (192, 192, 192), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "white": (255, 255, 255), "maroon": (128, 0, 0),
    "red": (255, 0, 0), "purple": (128, 0, 128), "fuchsia": (255, 0, 255),
    "magenta": (255, 0, 255), "green": (0, 128, 0), "lime": (0, 255, 0),
    "olive": (128, 128, 0), "yellow": (255, 255, 0), "navy": (0, 0, 128),
    "blue": (0, 0, 255), "teal": (0, 128, 128), "aqua": (0, 255, 255),
    "cyan": (0, 255, 255), "transparent": (255, 255, 255),
}


def _finding(check: str, severity: Severity, title: str, description: str,
            element: Tag | None = None) -> Finding:
    return Finding("accessibility", check, severity, title, description, snippet(element))


def analyze(html: str) -> list[Finding]:
    soup = BeautifulSoup(html, "lxml")
    findings: list[Finding] = []
    alt_text(soup, findings)
    headings(soup, findings)
    aria(soup, findings)
    landmarks(soup, findings)
    form_labels(soup, findings)
    keyboard(soup, findings)
    link_text(soup, findings)
    tables(soup, findings)
    iframes(soup, findings)
    viewport(soup, findings)
    language(soup, findings)
    color_contrast(soup, findings)
    media_captions(soup, findings)
    focus_indicator(soup, findings)
    return findings


def alt_text(soup: BeautifulSoup, out: list[Finding]) -> None:
    images = [img for img in soup.find_all("img") if img.get("alt") is None]
    if not images:
        return
    examples = "\n".join(
        f"  · <img src=\"{truncate(img.get('src', ''), 80)}\">" for img in images[:5]
    )
    out.append(Finding(
        "accessibility", "alt_text", Severity.ERROR,
        f"{len(images)} image(s) missing alt text",
        "Images without an alt attribute cannot be described to screen-reader users. "
        "Use alt=\"description\" for informative images, alt=\"\" for decorative ones, "
        "and never omit the attribute. WCAG 2.2 1.1.1 (A).\n\nExamples:\n" + examples,
        snippet(images[0]),
    ))


def headings(soup: BeautifulSoup, out: list[Finding]) -> None:
    tags = soup.find_all(re.compile(r"^h[1-6]$"))
    if not tags:
        out.append(Finding(
            "accessibility", "headings_outline", Severity.ERROR,
            "Page has no heading structure",
            "The document has no h1–h6 elements. Screen-reader users rely on headings "
            "to navigate. Add one h1 for the page title and h2/h3 for sections. "
            "WCAG 2.2 1.3.1 (A).",
        ))
        return
    previous = 0
    skipped = False
    outline: list[str] = []
    for tag in tags:
        level = int(tag.name[1])
        if level > previous + 1:
            skipped = True
        previous = level
        text = tag.get_text(" ", strip=True) or "(empty)"
        outline.append(f"<{tag.name}>{truncate(text, 80)}</{tag.name}>")
    if skipped:
        out.append(Finding(
            "accessibility", "headings_outline", Severity.WARNING,
            "Heading hierarchy skips one or more levels",
            "Headings jump levels (for example h1 → h3). Use a strict hierarchy. "
            "WCAG 2.2 1.3.1 (A), 2.4.6 (AA).\n\n" + "\n".join(outline),
            "\n".join(outline),
        ))


def aria(soup: BeautifulSoup, out: list[Finding]) -> None:
    for element in soup.select("[role=button], [role=link]"):
        native = element.name in ("button", "a")
        if not native and element.get("tabindex") is None:
            out.append(_finding(
                "aria_roles", Severity.ERROR,
                f"role='{element.get('role')}' on non-interactive element without tabindex",
                "The element is not keyboard-focusable. Use a native button/a element, "
                "or add tabindex=\"0\" and key handling. WCAG 2.2 4.1.2 (A).",
                element,
            ))
    if not soup.select("[role], [aria-label], [aria-labelledby], [aria-describedby]"):
        out.append(Finding(
            "accessibility", "aria_usage", Severity.INFO,
            "No ARIA attributes detected on the page",
            "No role, aria-label, aria-labelledby or aria-describedby was found. "
            "This is acceptable for simple static content, but complex widgets need ARIA.",
        ))


def landmarks(soup: BeautifulSoup, out: list[Finding]) -> None:
    selectors = {
        "header/banner": "header, [role=banner]",
        "nav/navigation": "nav, [role=navigation]",
        "main": "main, [role=main]",
        "footer/contentinfo": "footer, [role=contentinfo]",
        "aside/complementary": "aside, [role=complementary]",
        "search": "form[aria-label], form[aria-labelledby], [role=search]",
    }
    present = [name for name, sel in selectors.items() if soup.select_one(sel)]
    absent = [name for name, sel in selectors.items() if not soup.select_one(sel)]
    if not present:
        out.append(Finding(
            "accessibility", "landmarks", Severity.WARNING,
            "No landmark regions found on the page",
            "Add header, nav, main and footer landmarks so screen-reader users can jump "
            "between page regions. WCAG 2.2 1.3.1 (A).",
        ))
    elif absent:
        out.append(Finding(
            "accessibility", "landmarks", Severity.INFO,
            "Some landmark regions are missing",
            "Present: " + ", ".join(present) + "\nMissing: " + ", ".join(absent) +
            "\nWCAG 2.2 1.3.1 (A).",
        ))


def form_labels(soup: BeautifulSoup, out: list[Finding]) -> None:
    controls = soup.select(
        "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]),"
        "select,textarea"
    )
    label_for = {label.get("for") for label in soup.select("label[for]") if label.get("for")}
    unlabeled: list[Tag] = []
    for control in controls:
        cid = control.get("id")
        if cid and cid in label_for:
            continue
        if control.find_parent("label") is not None:
            continue
        if control.get("aria-label") or control.get("aria-labelledby"):
            continue
        unlabeled.append(control)
    if not unlabeled:
        return
    examples = "\n".join(f"  · {truncate(str(c), 140)}" for c in unlabeled[:5])
    out.append(Finding(
        "accessibility", "form_labels", Severity.ERROR,
        f"{len(unlabeled)} form control(s) without an accessible label",
        "Associate each control with <label for>, wrap it in <label>, or use "
        "aria-label/aria-labelledby. WCAG 2.2 3.3.2 and 4.1.2 (A).\n\n" + examples,
        snippet(unlabeled[0]),
    ))


def keyboard(soup: BeautifulSoup, out: list[Finding]) -> None:
    positive = []
    for element in soup.select("[tabindex]"):
        try:
            value = int(element.get("tabindex", "0"))
        except ValueError:
            continue
        if value > 0:
            positive.append(element)
            if len(positive) >= 5:
                break
    if positive:
        out.append(Finding(
            "accessibility", "keyboard_nav", Severity.WARNING,
            f"{len(positive)} element(s) with positive tabindex values found",
            "Positive tabindex values override the natural focus order. Use tabindex=\"0\" "
            "or reorder the DOM. WCAG 2.2 2.4.3 (A).",
            snippet(positive[0]),
        ))


def link_text(soup: BeautifulSoup, out: list[Finding]) -> None:
    for anchor in soup.select("a[href]"):
        text = anchor.get_text(" ", strip=True).lower()
        if len(text) < 2:
            continue
        if any(text == generic or text.startswith(generic + " ") for generic in GENERIC_LINKS):
            out.append(Finding(
                "accessibility", "link_text", Severity.WARNING,
                "Link text is generic or non-descriptive",
                f"Link text \"{truncate(text, 80)}\" does not explain its destination. "
                "Use descriptive text that makes sense out of context. WCAG 2.2 2.4.4 (A).",
                snippet(anchor),
            ))


def tables(soup: BeautifulSoup, out: list[Finding]) -> None:
    for table in soup.find_all("table"):
        headers = table.find_all("th")
        if not headers:
            continue
        if table.find("caption") is None:
            out.append(Finding(
                "accessibility", "tables", Severity.INFO,
                "Data table lacks a <caption>",
                "A caption gives screen-reader users context before entering the table. "
                "WCAG 2.2 1.3.1 (A).",
                snippet(table),
            ))
        if len(table.select("th[scope]")) < len(headers):
            out.append(Finding(
                "accessibility", "tables", Severity.WARNING,
                "Table <th> cells missing scope attribute",
                "Add scope=\"col\" to column headers and scope=\"row\" to row headers. "
                "WCAG 2.2 1.3.1 (A).",
                snippet(table),
            ))


def iframes(soup: BeautifulSoup, out: list[Finding]) -> None:
    for frame in soup.find_all("iframe"):
        src = frame.get("src", "")
        if src.startswith("data:"):
            continue
        if not (frame.get("title") or "").strip():
            out.append(Finding(
                "accessibility", "iframes", Severity.WARNING,
                "Iframe missing or has an empty title attribute",
                "Add title=\"description of the embedded content\" so screen readers can "
                "announce it. WCAG 2.2 4.1.2 (A).",
                snippet(frame),
            ))


def viewport(soup: BeautifulSoup, out: list[Finding]) -> None:
    meta = soup.find("meta", attrs={"name": re.compile("^viewport$", re.IGNORECASE)})
    if meta is None:
        out.append(Finding(
            "accessibility", "viewport", Severity.WARNING,
            "Missing viewport meta tag",
            "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"> "
            "so mobile browsers do not shrink the page. WCAG 2.2 1.4.4 (AA).",
        ))
        return
    content = (meta.get("content") or "").lower()
    blocked = (
        "user-scalable=no" in content
        or "user-scalable=0" in content
        or re.search(r"maximum-scale\s*=\s*1(?:\.0+)?(?:\D|$)", content) is not None
    )
    if blocked:
        out.append(Finding(
            "accessibility", "viewport", Severity.WARNING,
            "Viewport meta tag prevents user zoom",
            "Remove user-scalable=no and maximum-scale=1 so low-vision users can zoom. "
            "WCAG 2.2 1.4.4 (AA).",
            snippet(meta),
        ))


def language(soup: BeautifulSoup, out: list[Finding]) -> None:
    html_tag = soup.find("html")
    if html_tag is None:
        return
    lang = (html_tag.get("lang") or html_tag.get("xml:lang") or "").strip()
    if not lang:
        out.append(Finding(
            "accessibility", "lang_attribute", Severity.ERROR,
            "<html> element missing lang attribute",
            "Add lang=\"en\" (or the correct language code) so assistive technology "
            "selects the right voice and pronunciation. WCAG 2.2 3.1.1 (A).",
            snippet(html_tag),
        ))


def media_captions(soup: BeautifulSoup, out: list[Finding]) -> None:
    media = soup.find_all(["video", "audio"])
    if not media:
        return
    missing = 0
    examples: list[str] = []
    for element in media:
        has_track = element.find(
            "track", attrs={"kind": re.compile("^(captions|subtitles)$", re.IGNORECASE)}
        ) is not None
        if not has_track:
            missing += 1
            if len(examples) < 5:
                examples.append(
                    f"  · <{element.name} src=\"{truncate(element.get('src', ''), 80)}\">"
                )
    if missing:
        out.append(Finding(
            "accessibility", "media_captions", Severity.WARNING,
            f"{missing} media element(s) missing captions or subtitles",
            "Add a <track kind=\"captions\" ...> for prerecorded media. "
            "WCAG 2.2 1.2.2 (A).\n\n" + "\n".join(examples),
        ))


def focus_indicator(soup: BeautifulSoup, out: list[Finding]) -> None:
    examples = []
    for element in soup.select(
        "a[href],button,input:not([type=hidden]),select,textarea,[tabindex],[contenteditable]"
    ):
        style = element.get("style") or ""
        match = re.search(r"outline\s*:\s*(none|0)(?:\s|;|$)", style.lower())
        if match:
            examples.append(element)
            if len(examples) >= 5:
                break
    if examples:
        out.append(Finding(
            "accessibility", "focus_indicator", Severity.WARNING,
            f"{len(examples)} focusable element(s) have outline:none in inline style",
            "Never remove the focus outline without a visible replacement. "
            "Use outline: 2px solid …; outline-offset: 2px. WCAG 2.2 2.4.7 (AA).",
            snippet(examples[0]),
        ))


# --- Color contrast (static approximation) ---------------------------------

def _parse_color(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lower()
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) == 3:
            return tuple(int(ch * 2, 16) for ch in raw)  # type: ignore[return-value]
        if len(raw) == 6:
            return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        return None
    if value.startswith("rgb"):
        numbers = re.findall(r"[\d.]+", value)
        if len(numbers) >= 3:
            return tuple(int(float(n)) for n in numbers[:3])  # type: ignore[return-value]
        return None
    return NAMED_COLORS.get(value)


def _decl(style: str, name: str) -> str | None:
    for part in style.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            if key.strip().lower() == name:
                return value.strip()
    return None


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    l1, l2 = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _style_rules(soup: BeautifulSoup) -> list[tuple[str, dict[str, str]]]:
    rules: list[tuple[str, dict[str, str]]] = []
    for style_tag in soup.find_all("style"):
        css = style_tag.get_text()
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            declarations = {}
            for part in body.split(";"):
                if ":" in part:
                    key, value = part.split(":", 1)
                    declarations[key.strip().lower()] = value.strip()
            for selector in selectors.split(","):
                selector = selector.strip()
                if selector and not selector.startswith("@"):
                    rules.append((selector, declarations))
    return rules


def _matched_style(element: Tag, rules: list[tuple[str, dict[str, str]]]) -> dict[str, str]:
    style: dict[str, str] = {}
    for selector, declarations in rules:
        try:
            if element in element.parent.select(selector):
                style.update(declarations)
        except Exception:
            continue
    inline = element.get("style") or ""
    for part in inline.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            style[key.strip().lower()] = value.strip()
    return style


def _inherited(element: Tag, rules: list[tuple[str, dict[str, str]]], prop: str):
    current = element
    while current is not None and getattr(current, "name", None):
        style = _matched_style(current, rules)
        if prop in style:
            parsed = _parse_color(style[prop])
            if parsed:
                return parsed
        current = current.parent
    return None


def color_contrast(soup: BeautifulSoup, out: list[Finding]) -> None:
    rules = _style_rules(soup)
    examples: list[str] = []
    unmeasurable: list[str] = []
    for element in soup.find_all(TEXT_TAGS):
        style = _matched_style(element, rules)
        if "background-image" in style or (element.get("style") or "").find("background-image") >= 0:
            unmeasurable.append(f"<{element.name}> \"{truncate(element.get_text(' ', strip=True), 40)}\"")
            continue
        fg = _parse_color(style.get("color", "")) or _inherited(element, rules, "color") or (0, 0, 0)
        bg = _parse_color(style.get("background-color", "")) or _inherited(element, rules, "background-color") or (255, 255, 255)
        ratio = _contrast(fg, bg)
        font_size = style.get("font-size", "16px")
        try:
            size = float(re.sub(r"[^\d.]", "", font_size) or 16)
            if font_size.endswith("pt"):
                size *= 1.333
        except ValueError:
            size = 16
        large = size >= 24 or (size >= 18.66 and style.get("font-weight", "") in ("bold", "700", "800", "900"))
        threshold = 3.0 if large else 4.5
        if ratio < threshold and len(examples) < 10:
            examples.append(
                f"#{fg[0]:02x}{fg[1]:02x}{fg[2]:02x} on "
                f"#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x} → {ratio:.2f}:1"
            )
    if unmeasurable:
        out.append(Finding(
            "accessibility", "color_contrast_bg_image", Severity.INFO,
            f"{len(unmeasurable)} element(s) use background-image — contrast cannot be measured statically",
            "A browser-based audit is required for text over images. WCAG 2.2 1.4.3 (AA).\n\n"
            + "\n".join("  · " + item for item in unmeasurable[:5]),
        ))
    if examples:
        out.append(Finding(
            "accessibility", "color_contrast", Severity.WARNING,
            f"{len(examples)} element(s) with insufficient color contrast",
            "WCAG 2.2 AA requires 4.5:1 for normal text and 3:1 for large text. "
            "This is a static approximation; external CSS and browser states are not "
            "fully evaluated. Examples:\n" + "\n".join("  · " + item for item in examples),
        ))
