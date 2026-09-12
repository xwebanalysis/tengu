import { Component, Input } from '@angular/core';

import { FindingView } from '../../core/models';
import { highlightHtmlLine, htmlLines, lineMatchesSnippet } from '../../core/snippet-locator';

/**
 * Pretty HTML source viewer with tag/attribute highlighting and finding
 * line-highlighting. The backend sends the pretty-printed source through the
 * `log` event (`html_source`).
 */
@Component({
  selector: 'app-html-viewer',
  template: `
    <div class="html-source">
      @for (line of lines; track $index) {
        <div class="source-line" [class.highlight]="isHighlighted($index)">
          <span class="line-num">{{ $index + 1 }}</span>
          <span class="line-html" [innerHTML]="highlight(line)"></span>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .html-source {
        font-family: var(--font-data);
        font-size: var(--caption);
        max-height: 600px;
        overflow-y: auto;
        overflow-x: hidden;
        border: 1px solid var(--border);
        line-height: 1.6;
      }

      .source-line {
        display: flex;
        gap: var(--space-md);
        padding: 0 var(--space-sm);
        border-left: 4px solid transparent;
        word-break: break-all;
      }

      .source-line:hover {
        background: var(--surface-raised);
      }

      .source-line.highlight {
        background: var(--accent-subtle);
        border-left: 4px solid var(--accent);
      }

      .line-num {
        color: var(--text-disabled);
        min-width: 48px;
        text-align: right;
        user-select: none;
        border-right: 1px solid var(--border);
        padding-right: var(--space-sm);
        flex-shrink: 0;
      }

      .line-html {
        color: var(--text-primary);
        white-space: pre-wrap;
        word-break: break-all;
        overflow-wrap: break-word;
      }

      :host ::ng-deep .syn-tag {
        color: var(--interactive);
      }
      :host ::ng-deep .syn-attr {
        color: var(--warning);
      }
      :host ::ng-deep .syn-val {
        color: var(--success);
      }
      :host ::ng-deep .syn-punc {
        color: var(--text-disabled);
      }
    `,
  ],
})
export class HtmlViewerComponent {
  @Input() html = '';
  @Input() findings: readonly FindingView[] = [];

  get lines(): string[] {
    return htmlLines(this.html);
  }

  isHighlighted(index: number): boolean {
    const line = this.lines[index];
    if (!line) {
      return false;
    }
    return this.findings.some((finding) => lineMatchesSnippet(line, finding.snippet));
  }

  highlight(line: string): string {
    return highlightHtmlLine(line);
  }
}
