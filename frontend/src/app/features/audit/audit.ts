import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ApiService } from '../../core/api.service';
import {
  LiveEvent,
  findingFromEvent,
  htmlFromEvent,
  logLineFromEvent,
  pageFromEvent,
} from '../../core/events';
import { ExportService, AuditExportContext } from '../../core/export.service';
import { TranslateService } from '../../core/i18n.service';
import { LiveService } from '../../core/live.service';
import { AuditMode, AuditRequest, FindingView, Severity, severityCounts } from '../../core/models';
import { htmlLines, locateLine } from '../../core/snippet-locator';
import {
  XwaChartComponent,
  XwaChartColorKey,
  XwaChartDatum,
} from '../../shared/charts/xwa-chart.component';
import { ExportActionsComponent } from '../../shared/export-actions/export-actions';
import { HtmlViewerComponent } from '../../shared/html-viewer/html-viewer';
import { MetricCardComponent } from '../../shared/metric-card/metric-card';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { SeverityTagComponent } from '../../shared/severity-tag/severity-tag';
import { TerminalComponent } from '../../shared/terminal/terminal';

type CheckTab = 'all' | 'performance' | 'seo' | 'accessibility' | 'best_practices';

const SELECTED_CHECKS = ['performance', 'seo', 'accessibility', 'best_practices'];

@Component({
  selector: 'app-audit',
  imports: [
    FormsModule,
    ExportActionsComponent,
    HtmlViewerComponent,
    MetricCardComponent,
    SeverityTagComponent,
    TerminalComponent,
    TranslatePipe,
    XwaChartComponent,
  ],
  templateUrl: './audit.html',
  styleUrl: './audit.scss',
})
export class AuditComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly live = inject(LiveService);
  private readonly exporter = inject(ExportService);
  private readonly translate = inject(TranslateService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  readonly targetUrl = signal('');
  readonly auditMode = signal<AuditMode>('single');
  readonly includeSubdomains = signal(false);
  readonly batchUrl = signal('');
  readonly batchFormat = signal('sitemap');
  readonly checkTab = signal<CheckTab>('all');
  readonly filterTab = signal('all');
  readonly filterCheck = signal('all');
  readonly loadedId = signal<string | null>(null);

  readonly isRunning = signal(false);
  readonly isComplete = signal(false);
  readonly findings = signal<FindingView[]>([]);
  readonly pagesFound = signal<string[]>([]);
  readonly pageHtml = signal('');
  readonly htmlViewOpen = signal(false);
  readonly logs = signal<string[]>([]);
  readonly pdfBusy = signal(false);

  readonly summary = computed(() => severityCounts(this.findings()));

  /**
   * Category scores (0-100) for the four check categories, derived from
   * finding severities with the same weighting used by the Lighthouse
   * export. Colored by score: >=90 success, 60-89 warning, <60 accent.
   */
  readonly scoreChartData = computed<XwaChartDatum[]>(() => {
    const categories: Array<[string, string]> = [
      ['performance', this.translate.t('audit.performance')],
      ['seo', this.translate.t('audit.seo')],
      ['accessibility', this.translate.t('audit.accessibility')],
      ['best_practices', this.translate.t('audit.best_practices')],
    ];
    return categories.map(([category, label]) => {
      const items = this.findings().filter((finding) => finding.category === category);
      const high = items.filter((f) => f.severity === 'high' || f.severity === 'critical').length;
      const medium = items.filter((f) => f.severity === 'medium' || f.severity === 'low').length;
      const score = Math.round(100 * Math.max(0, 1 - (high * 0.3 + medium * 0.1)));
      const color: XwaChartColorKey = score >= 90 ? 'success' : score >= 60 ? 'warning' : 'critical';
      return { label, value: score, color };
    });
  });

  /** Issues by severity (XWA chart severity color mapping). */
  readonly severityChartData = computed<XwaChartDatum[]>(() => {
    const counts = this.summary();
    const mapping: Array<[Severity, XwaChartColorKey, string]> = [
      ['critical', 'critical', this.translate.t('audit.critical')],
      ['high', 'warning', this.translate.t('audit.high')],
      ['medium', 'neutral-strong', this.translate.t('audit.medium')],
      ['low', 'success', this.translate.t('audit.low')],
      ['info', 'interactive', this.translate.t('audit.info')],
    ];
    return mapping.map(([severity, color, label]) => ({
      label,
      value: counts[severity],
      color,
    }));
  });

  /** Issues by category (default categorical color sequence). */
  readonly categoryChartData = computed<XwaChartDatum[]>(() =>
    Object.entries(this.categoryCounts())
      .sort((a, b) => b[1] - a[1])
      .map(([category, value]) => ({ label: this.categoryLabel(category), value })),
  );

  readonly categories = computed(() => [...new Set(this.findings().map((f) => f.category))]);

  readonly categoryCounts = computed(() => {
    const counts: Record<string, number> = {};
    for (const finding of this.findings()) {
      counts[finding.category] = (counts[finding.category] ?? 0) + 1;
    }
    return counts;
  });

  readonly checkTypes = computed(() => {
    const tab = this.filterTab();
    const pool = tab === 'all' ? [] : this.findings().filter((f) => f.category === tab);
    return [...new Set(pool.map((f) => f.check))];
  });

  readonly filteredFindings = computed(() => {
    const tab = this.filterTab();
    const check = this.filterCheck();
    let items = this.findings();
    if (tab !== 'all') {
      items = items.filter((f) => f.category === tab);
    }
    if (check !== 'all') {
      items = items.filter((f) => f.check === check);
    }
    return items;
  });

  readonly hasCrawlOptions = computed(() => this.auditMode() === 'fullsite');
  readonly hasBatchOptions = computed(() => this.auditMode() === 'batch');

  ngOnInit(): void {
    this.route.queryParams.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params['load'];
      if (typeof id === 'string' && id) {
        this.loadAudit(id);
        return;
      }
      this.loadLatestAudit();
    });
  }

  /**
   * Dashboard mode: without a ?load= query parameter, show the most recent
   * completed analysis so the category score, severity and category charts
   * render with data on first paint.
   */
  private loadLatestAudit(): void {
    this.api
      .listAnalyses()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (records) => {
          const latest = [...records]
            .filter((record) => record.status === 'COMPLETED')
            .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
          if (latest) {
            this.loadAudit(latest.id);
          }
        },
        error: () => {
          // No history yet: stay in form-only mode.
        },
      });
  }

  loadAudit(id: string): void {
    this.loadedId.set(id);
    this.api
      .getAnalysis(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (record) => {
          this.targetUrl.set(record.url);
          this.findings.set(record.findings);
          this.isComplete.set(true);
          this.filterTab.set('all');
          this.filterCheck.set('all');
        },
        error: () => {
          this.logs.update((lines) => [...lines, `[!] ${this.translate.t('audit.load_error')}`]);
          this.finish();
        },
      });
  }

  startAudit(): void {
    let url = this.targetUrl().trim();
    if (!url) {
      return;
    }
    if (!/^https?:\/\//.test(url)) {
      url = `https://${url}`;
      this.targetUrl.set(url);
    }

    this.loadedId.set(null);
    this.isRunning.set(true);
    this.isComplete.set(false);
    this.findings.set([]);
    this.pagesFound.set([]);
    this.pageHtml.set('');
    this.logs.set([]);
    this.checkTab.set('all');
    this.filterTab.set('all');
    this.filterCheck.set('all');

    if (this.auditMode() === 'batch') {
      this.batchUrl.set(url);
    }

    const request: AuditRequest = {
      url: this.auditMode() === 'batch' ? this.batchUrl() : url,
      mode: this.auditMode(),
      subdomains: this.includeSubdomains(),
      checks: SELECTED_CHECKS,
      batchUrl: this.batchUrl(),
      batchFormat: this.batchFormat(),
    };

    this.live
      .connect(this.api.liveUrl(request))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => this.handleEvent(event),
        error: (error: unknown) => {
          const detail = error instanceof Error && error.message ? `: ${error.message}` : '';
          this.appendLog(`[!] ${this.translate.t('audit.ws_error')}${detail}`);
          this.finish();
        },
        complete: () => this.finish(),
      });
  }

  private handleEvent(event: LiveEvent): void {
    const page = pageFromEvent(event);
    if (page) {
      this.pagesFound.update((pages) => [...pages, page]);
      return;
    }

    const html = htmlFromEvent(event);
    if (html) {
      this.pageHtml.set(html);
      return;
    }

    const finding = findingFromEvent(event);
    if (finding) {
      this.findings.update((items) => [...items, finding]);
      return;
    }

    const line = logLineFromEvent(event);
    if (line) {
      this.appendLog(line);
    }

    if (event.type === 'analysis_started') {
      this.loadedId.set(event.analysis_id);
    }
    if (event.type === 'analysis_completed' || event.type === 'analysis_error') {
      this.finish();
    }
  }

  private appendLog(line: string): void {
    this.logs.update((lines) => [...lines, line]);
  }

  private finish(): void {
    this.isRunning.set(false);
    this.isComplete.set(true);
  }

  setCheckTab(tab: CheckTab): void {
    this.checkTab.set(tab);
    this.filterTab.set(tab === 'all' ? 'all' : tab);
    this.filterCheck.set('all');
  }

  setFilterTab(tab: string): void {
    this.filterTab.set(tab);
    this.filterCheck.set('all');
    if (tab === 'all' || tab === 'performance' || tab === 'seo' || tab === 'accessibility' || tab === 'best_practices') {
      this.checkTab.set(tab);
    }
  }

  setCheckFilter(check: string): void {
    this.filterCheck.set(check);
  }

  checkCount(check: string): number {
    return this.findings().filter((f) => f.category === this.filterTab() && f.check === check).length;
  }

  labelCheck(check: string): string {
    return check.replace(/_/g, ' ');
  }

  categoryLabel(category: string): string {
    return category.replace(/_/g, '-').toUpperCase();
  }

  findingLine(finding: FindingView): number {
    return locateLine(htmlLines(this.pageHtml()), finding.snippet);
  }

  toggleHtmlView(): void {
    this.htmlViewOpen.update((open) => !open);
  }

  /* ---- Client-side exports (all six formats) ---- */

  private effectiveUrl(): string {
    return this.auditMode() === 'batch' ? this.batchUrl() : this.targetUrl();
  }

  private exportContext(): AuditExportContext {
    return {
      mode: this.auditMode(),
      url: this.effectiveUrl(),
      subdomains: this.includeSubdomains(),
      findings: this.filteredFindings(),
      html: this.pageHtml(),
    };
  }

  exportCsv(): void {
    this.exporter.exportCsv(this.exportContext());
  }

  exportJson(): void {
    this.exporter.exportJson(this.exportContext());
  }

  exportLighthouse(): void {
    this.exporter.exportLighthouse(this.exportContext());
  }

  exportHtml(): void {
    this.exporter.exportHtml(this.exportContext());
  }

  exportMd(): void {
    this.exporter.exportMd(this.exportContext());
  }

  async exportPdf(): Promise<void> {
    if (this.pdfBusy()) {
      return;
    }
    this.pdfBusy.set(true);
    try {
      await this.exporter.exportPdf(this.exportContext());
    } finally {
      this.pdfBusy.set(false);
    }
  }
}
