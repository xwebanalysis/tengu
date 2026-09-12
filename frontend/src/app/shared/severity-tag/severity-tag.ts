import { Component, Input } from '@angular/core';

import { severityClass } from '../../core/models';

/**
 * Unified severity tag. Renders `[ SEVERITY ]` in Space Mono caps with the
 * data-status color applied to the value, never to a background.
 *
 * Mapping (xwa-sdk): `Pass -> pass`, `Info -> info`, `Warning -> medium`,
 * `Error -> high`; `low` and `critical` complete the shared scale.
 */
@Component({
  selector: 'app-severity-tag',
  template: `<span class="tag" [class]="tagClass()">[ {{ label }} ]</span>`,
  styles: [
    `
      .tag {
        font-family: var(--font-data);
        font-size: var(--caption);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        white-space: nowrap;
      }
    `,
  ],
})
export class SeverityTagComponent {
  @Input({ required: true }) severity = 'info';

  get label(): string {
    return String(this.severity).toUpperCase();
  }

  tagClass(): string {
    return severityClass(this.severity);
  }
}
