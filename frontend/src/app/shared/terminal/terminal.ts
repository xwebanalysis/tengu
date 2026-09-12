import { Component, ElementRef, Input, OnChanges, ViewChild } from '@angular/core';

/**
 * Nothing-style terminal: bracketed head, monospace body, auto-scroll.
 * No skeletons — live output is appended as text lines.
 */
@Component({
  selector: 'app-terminal',
  template: `
    <div class="terminal">
      <div class="terminal-head">
        <span class="t-label">{{ title }}</span>
        <span class="t-label">{{ isRunning ? liveText : lines.length + ' ' + unitText }}</span>
      </div>
      <div class="terminal-body" #scroller>
        @if (lines.length === 0 && !isRunning) {
          <div class="terminal-line terminal-empty t-data">{{ emptyText }}</div>
        } @else {
          @for (line of lines; track $index) {
            <div class="terminal-line t-data">
              <span class="terminal-prompt">$</span>
              <span class="terminal-msg">{{ line }}</span>
            </div>
          }
          @if (isRunning) {
            <div class="terminal-line t-data">
              <span class="terminal-prompt">$</span>
              <span class="terminal-cursor">▊</span>
            </div>
          }
        }
      </div>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        margin-bottom: var(--space-lg);
      }

      .terminal {
        border: 1px solid var(--border-visible);
        background-color: var(--black);
        font-family: var(--font-data);
      }

      .terminal-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--space-sm) var(--space-md);
        border-bottom: 1px solid var(--border);
        background-color: var(--surface);
      }

      .terminal-body {
        height: 240px;
        overflow-y: auto;
        padding: var(--space-sm) var(--space-md);
        display: flex;
        flex-direction: column;
        gap: 1px;
      }

      .terminal-line {
        display: flex;
        gap: var(--space-sm);
        align-items: baseline;
        font-size: var(--caption);
        line-height: 1.6;
      }

      .terminal-prompt {
        color: var(--success);
        flex-shrink: 0;
        user-select: none;
      }

      .terminal-msg {
        color: var(--text-primary);
        word-break: break-all;
        white-space: pre-wrap;
      }

      .terminal-empty {
        color: var(--text-disabled);
      }

      .terminal-cursor {
        color: var(--success);
        animation: blink 1s step-end infinite;
      }

      @keyframes blink {
        50% {
          opacity: 0;
        }
      }
    `,
  ],
})
export class TerminalComponent implements OnChanges {
  @Input() lines: string[] = [];
  @Input() title = 'TERMINAL';
  @Input() emptyText = '[ NO EVENTS YET ]';
  @Input() liveText = 'LIVE';
  @Input() unitText = 'LINES';
  @Input() isRunning = false;

  @ViewChild('scroller') private scroller?: ElementRef<HTMLElement>;

  ngOnChanges(): void {
    queueMicrotask(() => {
      const element = this.scroller?.nativeElement;
      if (element) {
        element.scrollTop = element.scrollHeight;
      }
    });
  }
}
