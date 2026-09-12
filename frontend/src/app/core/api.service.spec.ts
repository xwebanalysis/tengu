import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ApiService } from './api.service';
import { analysisFromContract, normalizeSeverity, severityClass, severityCounts } from './models';

describe('ApiService', () => {
  let service: ApiService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should GET the health endpoint', () => {
    service.health().subscribe((health) => {
      expect(health.service).toBe('tengu');
      expect(health.database).toBe('ok');
    });

    const request = httpMock.expectOne('http://localhost:8070/api/health');
    expect(request.request.method).toBe('GET');
    request.flush({ status: 'ok', service: 'tengu', version: '0.2.0', database: 'ok' });
  });

  it('should list analyses and map the xwa-sdk contract to the view model', () => {
    service.listAnalyses().subscribe((records) => {
      expect(records).toHaveLength(1);
      expect(records[0].id).toBe('audit-1');
      expect(records[0].url).toBe('https://example.com');
      expect(records[0].status).toBe('COMPLETED');
      expect(records[0].findings[0].severity).toBe('medium');
      expect(records[0].findings[0].page_url).toBe('https://example.com/page');
      expect(records[0].findings[0].snippet).toBe('<img src="a.png">');
    });

    const request = httpMock.expectOne('http://localhost:8070/api/analyses');
    expect(request.request.method).toBe('GET');
    request.flush([
      {
        id: 'audit-1',
        tool: 'tengu',
        target: 'https://example.com',
        status: 'COMPLETED',
        created_at: '2026-09-12T10:00:00Z',
        findings: [
          {
            tool: 'tengu',
            severity: 'medium',
            title: 'Missing alt',
            description: 'Images need alternate text',
            category: 'accessibility',
            check: 'alt_text',
            target_url: 'https://example.com/page',
            evidence: { snippet: '<img src="a.png">' },
          },
        ],
      },
    ]);
  });

  it('should fetch and delete a single analysis', () => {
    service.getAnalysis('audit-9').subscribe((record) => expect(record.url).toBe('https://x.dev'));
    const get = httpMock.expectOne('http://localhost:8070/api/analyses/audit-9');
    expect(get.request.method).toBe('GET');
    get.flush({ id: 'audit-9', target: 'https://x.dev', status: 'COMPLETED', created_at: '' });

    service.deleteAnalysis('audit-9').subscribe();
    const deletion = httpMock.expectOne('http://localhost:8070/api/analyses/audit-9');
    expect(deletion.request.method).toBe('DELETE');
    deletion.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('should clear history through the store-wide endpoint', () => {
    service.clearHistory().subscribe();
    const request = httpMock.expectOne('http://localhost:8070/api/audits/clear');
    expect(request.request.method).toBe('DELETE');
    request.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('should build server-side export URLs', () => {
    expect(service.exportUrl('audit-3', 'json')).toBe(
      'http://localhost:8070/api/analyses/audit-3/export?format=json',
    );
    expect(service.exportUrl('audit-3', 'csv')).toBe(
      'http://localhost:8070/api/analyses/audit-3/export?format=csv',
    );
  });

  it('should build the live WebSocket URL with encoded Event options', () => {
    const url = service.liveUrl({
      url: 'https://example.com/a b',
      mode: 'fullsite',
      subdomains: true,
      checks: ['seo', 'performance'],
    });
    expect(url).toContain('ws://localhost:8070/api/audit/live?');
    expect(url).toContain('url=https%3A%2F%2Fexample.com%2Fa+b');
    expect(url).toContain('mode=fullsite');
    expect(url).toContain('subdomains=true');
    expect(url).toContain('checks=seo%2Cperformance');
  });

  it('should include batch parameters for batch mode', () => {
    const url = service.liveUrl({
      url: 'https://example.com/sitemap.xml',
      mode: 'batch',
      subdomains: false,
      checks: ['seo'],
      batchUrl: 'https://example.com/sitemap.xml',
      batchFormat: 'csv',
    });
    expect(url).toContain('batch_url=https%3A%2F%2Fexample.com%2Fsitemap.xml');
    expect(url).toContain('batch_format=csv');
  });
});

describe('xwa-sdk contract adapters', () => {
  it('should map unified and legacy severities', () => {
    expect(normalizeSeverity('pass')).toBe('pass');
    expect(normalizeSeverity('info')).toBe('info');
    expect(normalizeSeverity('low')).toBe('low');
    expect(normalizeSeverity('medium')).toBe('medium');
    expect(normalizeSeverity('high')).toBe('high');
    expect(normalizeSeverity('critical')).toBe('critical');
    // Legacy Tengu labels still present in old records.
    expect(normalizeSeverity('Pass')).toBe('pass');
    expect(normalizeSeverity('Warning')).toBe('medium');
    expect(normalizeSeverity('Error')).toBe('high');
    expect(normalizeSeverity(undefined)).toBe('info');
    expect(severityClass('high')).toBe('sev-high');
    expect(severityClass('Warning')).toBe('sev-medium');
  });

  it('should map a contract analysis with optional fields missing', () => {
    const record = analysisFromContract({
      id: 'audit-5',
      target: 'https://example.com',
      status: 'RUNNING',
      created_at: '2026-09-12T10:00:00Z',
    });
    expect(record.findings).toEqual([]);
    expect(record.error).toBeNull();
  });

  it('should count severities', () => {
    const counts = severityCounts([
      { category: 'seo', check: 'a', severity: 'high', title: '', description: '' },
      { category: 'seo', check: 'b', severity: 'high', title: '', description: '' },
      { category: 'seo', check: 'c', severity: 'pass', title: '', description: '' },
    ]);
    expect(counts.high).toBe(2);
    expect(counts.pass).toBe(1);
    expect(counts.medium).toBe(0);
  });
});
