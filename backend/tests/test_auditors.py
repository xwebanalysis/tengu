from __future__ import annotations

from pathlib import Path

import pytest

from tengu.audit import a11y, best_practices, performance, seo
from tengu.models import Severity

FIXTURE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Hi</title>
  <style>.muted { color: #e8e8e8; background-color: #ffffff; }</style>
</head>
<body>
  <h1>Tengu fixture heading</h1>
  <h3>Skipped heading level</h3>
  <p class="muted">Low contrast paragraph.</p>
  <img src="/img/photo.png">
  <a href="/about.html">About</a>
  <a href="/index.html"></a>
  <form><input type="text" name="q"></form>
</body>
</html>"""


def test_a11y_core_findings():
    findings = a11y.analyze(FIXTURE)
    checks = {finding.check for finding in findings}
    assert "alt_text" in checks
    assert "form_labels" in checks
    assert "lang_attribute" in checks
    assert "headings_outline" in checks
    assert "color_contrast" in checks


def test_a11y_empty_link_is_not_currently_flagged():
    # Regression marker for a known gap: the Rust engine skipped text shorter than 2 chars.
    findings = a11y.analyze(FIXTURE)
    assert not any(finding.check == "link_text" for finding in findings)


def test_performance_page_weight():
    findings = performance.analyze("<html></html>", {}, "https://example.com/")
    weight = next(f for f in findings if f.check == "page_weight")
    assert weight.severity == Severity.PASS


def test_seo_missing_title():
    findings = seo.analyze("<html><head></head><body></body></html>", "https://example.com/")
    title = next(f for f in findings if f.check == "title")
    assert title.severity == Severity.ERROR


def test_best_practices_http_and_missing_headers():
    findings = best_practices.analyze("<html></html>", {}, "http://example.com/")
    checks = {f.check for f in findings}
    assert "https" in checks
    assert "security_headers" in checks
    assert "doctype" in checks


def test_fixture_file_matches_expected_findings():
    fixture = Path(__file__).resolve().parents[2] / "e2e" / "fixture" / "index.html"
    if not fixture.is_file():
        pytest.skip("e2e fixture not available")
    findings = a11y.analyze(fixture.read_text())
    checks = {f.check for f in findings}
    assert {"alt_text", "form_labels", "lang_attribute", "color_contrast"} <= checks
