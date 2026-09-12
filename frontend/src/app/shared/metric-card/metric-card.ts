import { Component, Input } from '@angular/core';

import { severityClass } from '../../core/models';

/**
 * Instrument-panel metric: label above, large value below. The value color
 * encodes data status (severity) — labels stay neutral.
 */
@Component({
  selector: 'app-metric-card',
  template: `
    <div class="metric">
      <span class="t-label metric-label">{{ label }}</span>
      <div class="metric-row">
        <span class="metric-value" [class]="valueClass()">{{ value }}</span>
        @if (unit) {
          <span class="t-label metric-unit">{{ unit }}</span>
        }
      </div>
    </div>
  `,
  styles: [
    `
      .metric {
        display: flex;
        flex-direction: column;
        gap: var(--space-sm);
        padding: var(--space-md);
        border: 1px solid var(--border-visible);
        background-color: var(--surface);
        min-width: 120px;
      }

      .metric-label {
        letter-spacing: 0.12em;
      }

      .metric-row {
        display: flex;
        align-items: baseline;
        gap: var(--space-xs);
      }

      .metric-value {
        font-family: var(--font-display);
        font-size: var(--display-md);
        line-height: 1.05;
        letter-spacing: -0.02em;
      }

      .metric-unit {
        letter-spacing: 0.12em;
      }
    `,
  ],
})
export class MetricCardComponent {
  @Input({ required: true }) label = '';
  @Input() value: string | number = '—';
  @Input() unit = '';
  @Input() severity = 'info';

  valueClass(): string {
    return severityClass(this.severity);
  }
}
