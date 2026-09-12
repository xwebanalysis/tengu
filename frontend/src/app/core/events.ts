/**
 * xwa-sdk `Event` envelope parsing.
 *
 * The backend `/api/audit/live` WebSocket emits JSON envelopes shaped like
 * `{seq, type, tool, analysis_id, ts, payload}`. These pure helpers turn raw
 * frames into typed events and extract the payloads used by the UI:
 *
 * - `analysis_started`   -> `{target, mode}`
 * - `analysis_progress`  -> `{message, percent?}` (`[PAGE] <url>` announces a crawled page)
 * - `log`                -> `{level, message, data}` (pretty HTML in `data.html`, message `html_source`)
 * - `item_found`         -> xwa-sdk `Finding`
 * - `analysis_completed` -> `{status, summary}`
 * - `analysis_error`     -> xwa-sdk `Error` `{code, message, detail, retryable}`
 */

import { ContractFinding, ContractSummary, FindingView, findingFromContract } from './models';

export type LiveEventType =
  | 'analysis_started'
  | 'analysis_progress'
  | 'item_found'
  | 'analysis_completed'
  | 'analysis_error'
  | 'log';

export interface LiveEvent {
  seq: number;
  type: LiveEventType | string;
  tool: string;
  analysis_id: string;
  ts: string;
  payload: unknown;
}

export interface StartedPayload {
  target?: string;
  mode?: string;
}

export interface ProgressPayload {
  message?: string;
  percent?: number;
}

export interface LogPayload {
  level?: string;
  message?: string;
  data?: { html?: string };
}

export interface CompletedPayload {
  status?: string;
  summary?: ContractSummary;
}

export interface ErrorPayload {
  code?: string;
  message?: string;
  detail?: unknown;
  retryable?: boolean;
}

const PAGE_PREFIX = '[PAGE] ';

/** Parse a raw WebSocket frame. Returns `null` for malformed frames. */
export function parseEvent(raw: unknown): LiveEvent | null {
  if (typeof raw !== 'string') {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const type = record['type'];
  const seq = record['seq'];
  const analysisId = record['analysis_id'];
  if (typeof type !== 'string' || typeof seq !== 'number' || typeof analysisId !== 'string') {
    return null;
  }
  return {
    seq,
    type,
    tool: typeof record['tool'] === 'string' ? record['tool'] : 'tengu',
    analysis_id: analysisId,
    ts: typeof record['ts'] === 'string' ? record['ts'] : '',
    payload: record['payload'] ?? null,
  };
}

function payloadOf<T>(event: LiveEvent): T {
  return (event.payload ?? {}) as T;
}

export function startedPayload(event: LiveEvent): StartedPayload | null {
  if (event.type !== 'analysis_started') {
    return null;
  }
  return payloadOf<StartedPayload>(event);
}

export function progressPayload(event: LiveEvent): ProgressPayload | null {
  if (event.type !== 'analysis_progress') {
    return null;
  }
  return payloadOf<ProgressPayload>(event);
}

export function logPayload(event: LiveEvent): LogPayload | null {
  if (event.type !== 'log') {
    return null;
  }
  return payloadOf<LogPayload>(event);
}

export function completedPayload(event: LiveEvent): CompletedPayload | null {
  if (event.type !== 'analysis_completed') {
    return null;
  }
  return payloadOf<CompletedPayload>(event);
}

export function errorPayload(event: LiveEvent): ErrorPayload | null {
  if (event.type !== 'analysis_error') {
    return null;
  }
  return payloadOf<ErrorPayload>(event);
}

/** `item_found` -> normalized finding; `null` for any other event type. */
export function findingFromEvent(event: LiveEvent): FindingView | null {
  if (event.type !== 'item_found') {
    return null;
  }
  return findingFromContract(event.payload as ContractFinding);
}

/** `analysis_progress` announcing a crawled page (`[PAGE] <url>`). */
export function pageFromEvent(event: LiveEvent): string | null {
  const progress = progressPayload(event);
  const message = progress?.message;
  if (!message || !message.startsWith(PAGE_PREFIX)) {
    return null;
  }
  const page = message.slice(PAGE_PREFIX.length).trim();
  return page.length > 0 ? page : null;
}

/** `log` event carrying the pretty-printed HTML source. */
export function htmlFromEvent(event: LiveEvent): string | null {
  const log = logPayload(event);
  if (!log || log.message !== 'html_source') {
    return null;
  }
  const html = log.data?.html;
  return typeof html === 'string' && html.length > 0 ? html : null;
}

/** Human readable terminal line for events that are not findings/HTML pages. */
export function logLineFromEvent(event: LiveEvent): string | null {
  switch (event.type) {
    case 'analysis_started': {
      const started = startedPayload(event);
      return `[AUDIT_META] target=${started?.target ?? '?'} mode=${started?.mode ?? '?'}`;
    }
    case 'analysis_progress': {
      const progress = progressPayload(event);
      const percent = typeof progress?.percent === 'number' ? ` (${progress.percent.toFixed(0)}%)` : '';
      return `[AUDIT] ${progress?.message ?? ''}${percent}`.trimEnd();
    }
    case 'log': {
      const log = logPayload(event);
      if (!log || log.message === 'html_source') {
        return null;
      }
      return `[${(log.level ?? 'info').toUpperCase()}] ${log.message ?? ''}`.trimEnd();
    }
    case 'analysis_completed':
      return '[done] analysis completed';
    case 'analysis_error': {
      const error = errorPayload(event);
      return `[!] ${error?.code ?? 'ERROR'}: ${error?.message ?? 'unknown error'}${
        error?.retryable ? ' (retryable)' : ''
      }`;
    }
    default:
      return `[EVENT] ${event.type}`;
  }
}
