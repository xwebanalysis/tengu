/**
 * Shared view models and xwa-sdk contract adapters.
 *
 * The backend speaks the xwa-sdk `Analysis` / `Finding` contracts: severity is
 * the unified lowercase scale (`pass`, `info`, `low`, `medium`, `high`,
 * `critical`) and findings carry `target_url` + `evidence`. The UI keeps a
 * normalized `FindingView` so templates, exports and comparisons work with one
 * stable shape.
 */

export type Severity = 'pass' | 'info' | 'low' | 'medium' | 'high' | 'critical';

export const SEVERITIES: readonly Severity[] = ['pass', 'info', 'low', 'medium', 'high', 'critical'];

/**
 * Normalize a severity coming from any source. Accepts the unified lowercase
 * scale and the legacy Tengu labels (`Error`, `Warning`, `Info`, `Pass`) so
 * previously persisted records keep rendering correctly.
 */
export function normalizeSeverity(raw: unknown): Severity {
  const value = typeof raw === 'string' ? raw.toLowerCase() : '';
  switch (value) {
    case 'pass':
    case 'passed':
      return 'pass';
    case 'info':
    case 'informational':
      return 'info';
    case 'low':
      return 'low';
    case 'medium':
    case 'warning':
    case 'warn':
      return 'medium';
    case 'high':
    case 'error':
      return 'high';
    case 'critical':
      return 'critical';
    default:
      return 'info';
  }
}

/** CSS helper class that colors the VALUE (never a background). */
export function severityClass(raw: unknown): string {
  return `sev-${normalizeSeverity(raw)}`;
}

export interface ContractEvidence {
  snippet?: string;
  [key: string]: unknown;
}

export interface ContractFinding {
  tool?: string;
  severity?: string;
  title?: string;
  description?: string;
  id?: string;
  category?: string;
  check?: string;
  target_url?: string;
  evidence?: ContractEvidence | string | null;
  confidence?: string;
  detected_at?: string;
}

export interface ContractSummary {
  total_items?: number;
  by_severity?: Record<string, number>;
  by_category?: Record<string, number>;
}

export interface ContractError {
  code?: string;
  message?: string;
  detail?: unknown;
  retryable?: boolean;
}

/** Flat analysis item returned by `/api/analyses` and `/api/analyses/{id}`. */
export interface ContractAnalysis {
  id: string;
  tool?: string;
  target?: string;
  status?: string;
  created_at?: string;
  tool_version?: string;
  analysis_type?: string;
  started_at?: string;
  finished_at?: string;
  error?: ContractError | null;
  summary?: ContractSummary | null;
  findings?: ContractFinding[];
}

/** Normalized finding used across the UI. */
export interface FindingView {
  category: string;
  check: string;
  severity: Severity;
  title: string;
  description: string;
  snippet?: string;
  page_url?: string;
  detected_at?: string;
}

/** Normalized analysis record used by the audit and history features. */
export interface AnalysisRecord {
  id: string;
  url: string;
  status: string;
  created_at: string;
  findings: FindingView[];
  tool?: string;
  toolVersion?: string;
  analysisType?: string;
  summary?: ContractSummary | null;
  error?: ContractError | null;
}

export interface HealthResponse {
  status: string;
  database: string;
  version: string;
  service?: string;
  tool?: string;
}

export type AuditMode = 'single' | 'fullsite' | 'batch';

export interface AuditRequest {
  url: string;
  mode: AuditMode;
  subdomains: boolean;
  checks: string[];
  batchUrl?: string;
  batchFormat?: string;
}

function snippetFromEvidence(evidence: ContractFinding['evidence']): string | undefined {
  if (typeof evidence === 'string') {
    return evidence;
  }
  if (evidence && typeof evidence === 'object' && typeof evidence.snippet === 'string') {
    return evidence.snippet;
  }
  return undefined;
}

/** Map an xwa-sdk `Finding` payload to the UI view model. */
export function findingFromContract(raw: unknown): FindingView {
  const finding = (raw ?? {}) as ContractFinding;
  return {
    category: finding.category ?? 'general',
    check: finding.check ?? 'unknown',
    severity: normalizeSeverity(finding.severity),
    title: finding.title ?? '—',
    description: finding.description ?? '',
    snippet: snippetFromEvidence(finding.evidence),
    page_url: finding.target_url,
    detected_at: finding.detected_at,
  };
}

/** Map an xwa-sdk `Analysis` payload (plus findings) to the UI view model. */
export function analysisFromContract(raw: unknown): AnalysisRecord {
  const analysis = (raw ?? {}) as ContractAnalysis;
  return {
    id: String(analysis.id ?? ''),
    url: analysis.target ?? '',
    status: analysis.status ?? 'COMPLETED',
    created_at: analysis.created_at ?? '',
    findings: (analysis.findings ?? []).map(findingFromContract),
    tool: analysis.tool,
    toolVersion: analysis.tool_version,
    analysisType: analysis.analysis_type,
    summary: analysis.summary,
    error: analysis.error ?? null,
  };
}

export function severityCounts(findings: readonly FindingView[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { pass: 0, info: 0, low: 0, medium: 0, high: 0, critical: 0 };
  for (const finding of findings) {
    counts[finding.severity] += 1;
  }
  return counts;
}

export function statusClass(status: string): string {
  switch (status.toUpperCase()) {
    case 'COMPLETED':
      return 'text-success';
    case 'RUNNING':
    case 'PENDING':
      return 'text-warning';
    case 'ERROR':
    case 'CANCELLED':
      return 'text-accent';
    default:
      return 'text-muted';
  }
}
