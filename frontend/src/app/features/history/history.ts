import { Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { TranslateService } from '../../core/i18n.service';
import { AnalysisRecord, Severity } from '../../core/models';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { StatusBadgeComponent } from '../../shared/status-badge/status-badge';

interface ComparisonResult {
  a: AnalysisRecord | null;
  b: AnalysisRecord | null;
  diff: string[];
}

interface TrendPoint {
  date: string;
  url: string;
  total: number;
  high: number;
  medium: number;
}

@Component({
  selector: 'app-history',
  imports: [RouterLink, StatusBadgeComponent, TranslatePipe],
  templateUrl: './history.html',
  styleUrl: './history.scss',
})
export class HistoryComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly translate = inject(TranslateService);
  private readonly destroyRef = inject(DestroyRef);

  readonly audits = signal<AnalysisRecord[]>([]);
  readonly isLoading = signal(false);
  readonly clearing = signal(false);
  readonly errorMessage = signal('');
  readonly compareMode = signal(false);
  readonly selectedIds = signal<Set<string>>(new Set());
  readonly comparisonResult = signal<ComparisonResult | null>(null);

  readonly scoreHistory = computed<TrendPoint[]>(() =>
    this.audits()
      .filter((audit) => audit.status === 'COMPLETED')
      .map((audit) => ({
        date: audit.created_at.slice(0, 10),
        url: audit.url,
        total: audit.findings.length,
        high: this.severityCount(audit, 'high'),
        medium: this.severityCount(audit, 'medium'),
      })),
  );

  readonly maxScore = computed(() => {
    const history = this.scoreHistory();
    if (history.length === 0) {
      return 1;
    }
    return Math.max(...history.map((point) => point.total + point.high + point.medium), 1);
  });

  readonly chartWidth = computed(() => Math.max(200, 40 + this.scoreHistory().length * 60));

  readonly stepX = computed(() => {
    const length = this.scoreHistory().length;
    return length > 1 ? (this.chartWidth() - 50) / (length - 1) : 0;
  });

  ngOnInit(): void {
    this.loadHistory();
  }

  loadHistory(): void {
    this.isLoading.set(true);
    this.errorMessage.set('');
    this.comparisonResult.set(null);

    this.api
      .listAnalyses()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (records) => {
          this.audits.set(
            [...records].sort((a, b) => b.created_at.localeCompare(a.created_at)),
          );
          this.isLoading.set(false);
        },
        error: (error: unknown) => {
          this.errorMessage.set(`${this.translate.t('history.load_error')}: ${this.errorDetail(error)}`);
          this.isLoading.set(false);
        },
      });
  }

  clearAll(): void {
    if (!confirm(this.translate.t('history.confirm_clear'))) {
      return;
    }
    this.clearing.set(true);
    this.api
      .clearHistory()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.audits.set([]);
          this.clearing.set(false);
          this.comparisonResult.set(null);
          this.selectedIds.set(new Set());
        },
        error: (error: unknown) => {
          this.errorMessage.set(`${this.translate.t('history.clear_error')}: ${this.errorDetail(error)}`);
          this.clearing.set(false);
        },
      });
  }

  toggleCompare(): void {
    this.compareMode.update((mode) => !mode);
    this.selectedIds.set(new Set());
    this.comparisonResult.set(null);
  }

  toggleSelection(id: string): void {
    const current = this.selectedIds();
    if (current.has(id)) {
      const next = new Set(current);
      next.delete(id);
      this.selectedIds.set(next);
      this.comparisonResult.set(null);
      return;
    }
    if (current.size >= 2) {
      return;
    }
    const next = new Set(current);
    next.add(id);
    this.selectedIds.set(next);
    if (next.size === 2) {
      this.runComparison(next);
    }
  }

  private runComparison(ids: Set<string>): void {
    const selected = [...ids];
    const a = this.audits().find((audit) => audit.id === selected[0]) ?? null;
    const b = this.audits().find((audit) => audit.id === selected[1]) ?? null;
    if (!a || !b) {
      this.comparisonResult.set(null);
      return;
    }

    const diff: string[] = [];
    for (const findingA of a.findings) {
      const match = b.findings.find(
        (findingB) => findingB.check === findingA.check && findingB.category === findingA.category,
      );
      if (!match) {
        diff.push(`[-] ${findingA.category}/${findingA.check} — present in A, fixed in B`);
      } else if (match.severity !== findingA.severity) {
        diff.push(
          `[~] ${findingA.category}/${findingA.check} — severity changed: ${findingA.severity} → ${match.severity}`,
        );
      }
    }
    for (const findingB of b.findings) {
      const match = a.findings.find(
        (findingA) => findingA.check === findingB.check && findingA.category === findingB.category,
      );
      if (!match) {
        diff.push(`[+] ${findingB.category}/${findingB.check} — new in B`);
      }
    }

    this.comparisonResult.set({ a, b, diff });
  }

  compareSeverityCount(record: AnalysisRecord | null, severity: Severity): number {
    return record ? this.severityCount(record, severity) : 0;
  }

  trendPoints(field: 'high' | 'medium' | 'total'): string {
    const max = this.maxScore() || 1;
    return this.scoreHistory()
      .map((point, index) => {
        const x = 40 + index * this.stepX();
        const y = 130 - (point[field] / max) * 100;
        return `${x},${y}`;
      })
      .join(' ');
  }

  private severityCount(record: AnalysisRecord, severity: Severity): number {
    return record.findings.filter((finding) => finding.severity === severity).length;
  }

  private errorDetail(error: unknown): string {
    if (error instanceof Error && error.message) {
      return error.message;
    }
    const status = (error as { status?: number } | null)?.status;
    return status ? `HTTP ${status}` : 'connection refused';
  }
}
