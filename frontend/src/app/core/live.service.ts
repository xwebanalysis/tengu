import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { LiveEvent, parseEvent } from './events';

/**
 * Thin WebSocket wrapper that exposes xwa-sdk `Event` envelopes as an
 * Observable. Server-side failures arrive as `analysis_error` events; transport
 * failures are surfaced through the Observable error channel.
 *
 * The backend closes the socket right after a terminal event
 * (`analysis_completed` / `analysis_error`) without a clean close frame, which
 * browsers report as an abnormal 1006 closure. Once a terminal event has been
 * seen, the close is treated as a normal completion so the UI does not append a
 * spurious transport error to the log.
 */
@Injectable({ providedIn: 'root' })
export class LiveService {
  connect(url: string): Observable<LiveEvent> {
    return new Observable<LiveEvent>((subscriber) => {
      const socket = new WebSocket(url);
      let terminal = false;

      socket.onmessage = (message) => {
        const event = parseEvent(message.data);
        if (event) {
          if (event.type === 'analysis_completed' || event.type === 'analysis_error') {
            terminal = true;
          }
          subscriber.next(event);
        }
      };

      socket.onerror = () => {
        subscriber.error(new Error('WebSocket transport error'));
      };

      socket.onclose = (event) => {
        if (event.wasClean || terminal) {
          subscriber.complete();
        } else {
          subscriber.error(new Error(`WebSocket closed with code ${event.code}`));
        }
      };

      return () => {
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
          socket.close(1000, 'client closed');
        }
      };
    });
  }
}
