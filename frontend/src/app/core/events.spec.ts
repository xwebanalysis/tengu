import {
  findingFromEvent,
  htmlFromEvent,
  logLineFromEvent,
  pageFromEvent,
  parseEvent,
  progressPayload,
} from './events';

const frame = (type: string, payload?: unknown, seq = 1): string =>
  JSON.stringify({
    seq,
    type,
    tool: 'tengu',
    analysis_id: 'audit-42',
    ts: '2026-09-12T10:00:00Z',
    ...(payload === undefined ? {} : { payload }),
  });

describe('parseEvent', () => {
  it('should parse a valid xwa-sdk Event envelope', () => {
    const event = parseEvent(frame('item_found', { title: 'Finding' }, 7));
    expect(event).not.toBeNull();
    expect(event?.seq).toBe(7);
    expect(event?.type).toBe('item_found');
    expect(event?.tool).toBe('tengu');
    expect(event?.analysis_id).toBe('audit-42');
    expect(event?.ts).toBe('2026-09-12T10:00:00Z');
  });

  it('should reject malformed or incomplete frames', () => {
    expect(parseEvent('not-json')).toBeNull();
    expect(parseEvent('[1,2,3]')).toBeNull();
    expect(parseEvent(JSON.stringify({ type: 'item_found' }))).toBeNull();
    expect(parseEvent(JSON.stringify({ seq: 1, analysis_id: 'a' }))).toBeNull();
    expect(parseEvent(JSON.stringify({ seq: '1', type: 'x', analysis_id: 'a' }))).toBeNull();
  });
});

describe('Event payload extraction', () => {
  it('should map item_found to a normalized finding', () => {
    const event = parseEvent(
      frame('item_found', {
        tool: 'tengu',
        severity: 'medium',
        title: 'Missing alt',
        description: 'Images need alternate text',
        category: 'accessibility',
        check: 'alt_text',
        target_url: 'https://example.com/page',
        evidence: { snippet: '<img src="a.png">' },
      }),
    )!;
    const finding = findingFromEvent(event);
    expect(finding).toEqual({
      category: 'accessibility',
      check: 'alt_text',
      severity: 'medium',
      title: 'Missing alt',
      description: 'Images need alternate text',
      snippet: '<img src="a.png">',
      page_url: 'https://example.com/page',
      detected_at: undefined,
    });
  });

  it('should not treat other events as findings', () => {
    expect(findingFromEvent(parseEvent(frame('analysis_started', {}))!)).toBeNull();
  });

  it('should extract pages from analysis_progress', () => {
    const page = parseEvent(frame('analysis_progress', { message: '[PAGE] https://example.com/a' }))!;
    expect(pageFromEvent(page)).toBe('https://example.com/a');

    const other = parseEvent(frame('analysis_progress', { message: 'Crawling 3 pages', percent: 40 }))!;
    expect(pageFromEvent(other)).toBeNull();
    expect(progressPayload(other)?.percent).toBe(40);
  });

  it('should extract pretty HTML from the html_source log event', () => {
    const html = parseEvent(
      frame('log', { level: 'debug', message: 'html_source', data: { html: '<html>\n<body></body>\n</html>' } }),
    )!;
    expect(htmlFromEvent(html)).toContain('<html>');

    const plainLog = parseEvent(frame('log', { level: 'info', message: 'fetching' }))!;
    expect(htmlFromEvent(plainLog)).toBeNull();
  });

  it('should build terminal lines for lifecycle events', () => {
    expect(logLineFromEvent(parseEvent(frame('analysis_started', { target: 'https://x', mode: 'single' }))!)).toBe(
      '[AUDIT_META] target=https://x mode=single',
    );
    expect(logLineFromEvent(parseEvent(frame('analysis_progress', { message: 'Analyzing', percent: 10.4 }))!)).toBe(
      '[AUDIT] Analyzing (10%)',
    );
    expect(logLineFromEvent(parseEvent(frame('log', { level: 'warn', message: 'robots denied' }))!)).toBe(
      '[WARN] robots denied',
    );
    expect(logLineFromEvent(parseEvent(frame('analysis_completed', { status: 'COMPLETED' }))!)).toBe(
      '[done] analysis completed',
    );
    expect(
      logLineFromEvent(
        parseEvent(frame('analysis_error', { code: 'TIMEOUT', message: 'took too long', retryable: true }))!,
      ),
    ).toBe('[!] TIMEOUT: took too long (retryable)');
  });

  it('should still log html_source events as null terminal lines', () => {
    const event = parseEvent(frame('log', { level: 'debug', message: 'html_source', data: { html: '<p/>' } }))!;
    expect(logLineFromEvent(event)).toBeNull();
  });
});
