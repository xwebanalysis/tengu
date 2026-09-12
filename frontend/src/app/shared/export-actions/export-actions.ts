import { Component, EventEmitter, Input, Output } from '@angular/core';

import { TranslatePipe } from '../pipes/translate.pipe';

/**
 * Export toolbar. Emits one event per client-side format; the audit feature
 * wires them to `ExportService`. Buttons are text-only (Nothing: no filled
 * icons, no emoji).
 */
@Component({
  selector: 'app-export-actions',
  imports: [TranslatePipe],
  template: `
    @if (hasExports) {
      <div class="export-actions">
        <span class="t-label export-label">{{ findingCount }} {{ 'audit.findings' | t }}</span>
        <button type="button" class="export-btn" (click)="exportCsv.emit()">
          {{ 'audit.export_csv' | t }}
        </button>
        <button type="button" class="export-btn" (click)="exportJson.emit()">
          {{ 'audit.export_json' | t }}
        </button>
        <button type="button" class="export-btn" (click)="exportLighthouse.emit()">
          {{ 'audit.export_lh' | t }}
        </button>
        <button type="button" class="export-btn" (click)="exportHtml.emit()">
          {{ 'audit.export_html' | t }}
        </button>
        <button type="button" class="export-btn" (click)="exportMd.emit()">
          {{ 'audit.export_md' | t }}
        </button>
        <button
          type="button"
          class="export-btn"
          (click)="exportPdf.emit()"
          [disabled]="pdfBusy"
        >
          {{ pdfBusy ? 'PDF...' : ('audit.export_pdf' | t) }}
        </button>
      </div>
    }
  `,
  styles: [
    `
      .export-actions {
        display: flex;
        align-items: center;
        gap: var(--space-sm);
        flex-wrap: wrap;
        margin-top: var(--space-lg);
        padding-top: var(--space-md);
        border-top: 1px solid var(--border);
      }

      .export-label {
        margin-right: var(--space-sm);
      }

      .export-btn {
        border: 1px solid var(--border-visible);
        background-color: transparent;
        color: var(--text-secondary);
        padding: var(--space-sm) var(--space-md);
        font-family: var(--font-data);
        font-size: var(--label);
        letter-spacing: 0.08em;
        text-transform: uppercase;
        min-height: 36px;
        cursor: pointer;

        &:hover:not(:disabled) {
          color: var(--gold);
          border-color: var(--gold);
          opacity: 1;
        }

        &:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
      }
    `,
  ],
})
export class ExportActionsComponent {
  @Input() hasExports = false;
  @Input() findingCount = 0;
  @Input() pdfBusy = false;

  @Output() exportCsv = new EventEmitter<void>();
  @Output() exportJson = new EventEmitter<void>();
  @Output() exportLighthouse = new EventEmitter<void>();
  @Output() exportPdf = new EventEmitter<void>();
  @Output() exportHtml = new EventEmitter<void>();
  @Output() exportMd = new EventEmitter<void>();
}
