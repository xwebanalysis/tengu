"""Audit orchestration: single page, full-site crawl and batch sources."""

from __future__ import annotations

import asyncio
import random

from ..config import AuditOptions, Config, normalize_url
from ..events import EventEmitter
from ..http import (
    HttpClient,
    crawl_site,
    fetch_batch_urls,
)
from ..models import Finding
from . import a11y, best_practices, performance, seo


async def run_audit(
    options: AuditOptions, emitter: EventEmitter, cfg: Config
) -> list[Finding]:
    url = normalize_url(options.url)
    opts = AuditOptions(
        url=url,
        mode=options.mode,
        subdomains=options.subdomains,
        checks=options.checks,
        batch_url=options.batch_url,
        batch_format=options.batch_format,
    )
    client = HttpClient(cfg)
    try:
        if opts.is_batch():
            source = opts.batch_url or opts.url
            await emitter.progress(f"Fetching batch URLs from {source}...")
            urls = await fetch_batch_urls(client, source, opts.batch_format)
            await emitter.progress(f"Found {len(urls)} URLs in batch")
        elif opts.is_full_site():
            await emitter.progress(f"Crawling {opts.url} for pages...")
            urls = await crawl_site(
                client,
                opts.url,
                opts.subdomains,
                cfg,
                on_page=lambda page: emitter.progress(f"[PAGE] {page}"),
                on_progress=lambda message: emitter.progress(message),
            )
            await emitter.progress(f"Found {len(urls)} pages to analyze")
        else:
            urls = [opts.url]

        total = max(1, len(urls))
        findings: list[Finding] = []
        for index, page_url in enumerate(urls):
            if index > 0:
                delay = random.randint(cfg.crawl_delay_min_ms, cfg.crawl_delay_max_ms) / 1000
                await asyncio.sleep(delay)
            percent = ((index + 1) / total) * 100
            await emitter.progress(f"Analyzing {page_url}", percent)
            try:
                page_findings = await analyze_page(page_url, opts, client, cfg, emitter)
                findings.extend(page_findings)
            except Exception as exc:
                await emitter.progress(f"Error on {page_url}: {exc}", percent)
        return findings
    finally:
        await client.close()


async def analyze_page(
    page_url: str,
    options: AuditOptions,
    client: HttpClient,
    cfg: Config,
    emitter: EventEmitter,
) -> list[Finding]:
    result = await client.fetch(page_url)
    await emitter.progress(f"{page_url} (HTTP {result.status_code})")

    findings: list[Finding] = []
    html = result.text

    if options.has_check("performance"):
        findings.extend(performance.analyze(html, result.headers, page_url))
    if options.has_check("seo"):
        findings.extend(seo.analyze(html, page_url))
        findings.extend(await seo.analyze_network(client, page_url, html, cfg))
    if options.has_check("accessibility"):
        findings.extend(a11y.analyze(html))
    if options.has_check("best_practices"):
        findings.extend(best_practices.analyze(html, result.headers, page_url))

    for finding in findings:
        if finding.page_url is None:
            finding.page_url = page_url
        await emitter.item_found(finding)

    await emitter.log("debug", "html_source", {"html": html})
    return findings
