import { Component, Input } from '@angular/core';

import { statusClass } from '../../core/models';

/** Analysis lifecycle badge (`PENDING|RUNNING|COMPLETED|ERROR|CANCELLED`). */
@Component({
  selector: 'app-status-badge',
  template: `<span class="t-label badge" [class]="badgeClass()">[ {{ status }} ]</span>`,
  styles: [
    `
      .badge {
        letter-spacing: 0.12em;
        white-space: nowrap;
      }
    `,
  ],
})
export class StatusBadgeComponent {
  @Input({ required: true }) status = '';

  badgeClass(): string {
    return statusClass(this.status);
  }
}
