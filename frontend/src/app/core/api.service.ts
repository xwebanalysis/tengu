import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';

import { environment } from '../../environments/environment';
import { AnalysisRecord, AuditRequest, HealthResponse, analysisFromContract } from './models';

export type ExportFormat = 'json' | 'csv';

/**
 * Single HTTP entry point for the app. All backend URLs are built here from
 * `environment.apiBaseUrl` — no hardcoded hosts or ports anywhere else.
 *
 * The authoritative history contract is `/api/analyses*` (xwa-sdk `Analysis`
 * views). `/api/audits/clear` is kept as the bulk-clear endpoint because the
 * backend does not expose `DELETE /api/analyses`; both read the same store.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  readonly apiBaseUrl = environment.apiBaseUrl;
  readonly wsBaseUrl = environment.wsBaseUrl;

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.apiBaseUrl}/api/health`);
  }

  listAnalyses(): Observable<AnalysisRecord[]> {
    return this.http
      .get<unknown[]>(`${this.apiBaseUrl}/api/analyses`)
      .pipe(map((items) => (Array.isArray(items) ? items.map(analysisFromContract) : [])));
  }

  getAnalysis(id: string): Observable<AnalysisRecord> {
    return this.http
      .get<unknown>(`${this.apiBaseUrl}/api/analyses/${encodeURIComponent(id)}`)
      .pipe(map(analysisFromContract));
  }

  deleteAnalysis(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiBaseUrl}/api/analyses/${encodeURIComponent(id)}`);
  }

  clearHistory(): Observable<void> {
    return this.http.delete<void>(`${this.apiBaseUrl}/api/audits/clear`);
  }

  /** Server-side export URL (Content-Disposition attachment). */
  exportUrl(id: string, format: ExportFormat = 'json'): string {
    return `${this.apiBaseUrl}/api/analyses/${encodeURIComponent(id)}/export?format=${format}`;
  }

  /** Live WebSocket endpoint (xwa-sdk `Event` envelopes). */
  liveUrl(request: AuditRequest): string {
    const params = new URLSearchParams({
      url: request.url,
      mode: request.mode,
      subdomains: String(request.subdomains),
      checks: request.checks.join(','),
    });
    if (request.mode === 'batch') {
      params.set('batch_url', request.batchUrl ?? request.url);
      params.set('batch_format', request.batchFormat ?? 'sitemap');
    }
    return `${this.wsBaseUrl}/api/audit/live?${params.toString()}`;
  }
}
