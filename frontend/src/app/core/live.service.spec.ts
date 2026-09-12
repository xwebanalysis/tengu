import { LiveService } from './live.service';

interface FakeFrame {
  data: string;
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = 0;
  onmessage: ((message: FakeFrame) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { wasClean: boolean; code: number }) => void) | null = null;
  closeCalls = 0;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closeCalls += 1;
    this.readyState = 3;
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  drop(code = 1006, wasClean = false): void {
    this.onclose?.({ wasClean, code });
  }

  failTransport(): void {
    this.onerror?.();
  }
}

function envelope(type: string, seq = 1): unknown {
  return { seq, type, tool: 'tengu', analysis_id: 'audit-1', ts: '', payload: {} };
}

describe('LiveService', () => {
  const originalWebSocket = (globalThis as { WebSocket?: unknown }).WebSocket;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    (globalThis as { WebSocket?: unknown }).WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    (globalThis as { WebSocket?: unknown }).WebSocket = originalWebSocket;
  });

  it('completes without error when the socket drops after a terminal event', () => {
    const service = new LiveService();
    const types: string[] = [];
    let completed = false;
    let errored = false;

    const subscription = service.connect('ws://tengu.test/api/audit/live').subscribe({
      next: (event) => types.push(event.type),
      complete: () => (completed = true),
      error: () => (errored = true),
    });

    const socket = FakeWebSocket.instances[0];
    socket.emit(envelope('item_found', 1));
    socket.emit(envelope('analysis_completed', 2));
    socket.drop();

    expect(types).toEqual(['item_found', 'analysis_completed']);
    expect(completed).toBe(true);
    expect(errored).toBe(false);
    subscription.unsubscribe();
  });

  it('still surfaces a transport error when no terminal event was received', () => {
    const service = new LiveService();
    let completed = false;
    let errorMessage = '';

    const subscription = service.connect('ws://tengu.test/api/audit/live').subscribe({
      complete: () => (completed = true),
      error: (error: Error) => (errorMessage = error.message),
    });

    const socket = FakeWebSocket.instances[0];
    socket.emit(envelope('analysis_started', 1));
    socket.drop();

    expect(completed).toBe(false);
    expect(errorMessage).toContain('1006');
    subscription.unsubscribe();
  });

  it('surfaces the transport error channel for socket errors', () => {
    const service = new LiveService();
    let errorMessage = '';

    const subscription = service.connect('ws://tengu.test/api/audit/live').subscribe({
      error: (error: Error) => (errorMessage = error.message),
    });

    FakeWebSocket.instances[0].failTransport();

    expect(errorMessage).toBe('WebSocket transport error');
    subscription.unsubscribe();
  });
});
