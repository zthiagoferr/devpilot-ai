import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: ` <span [class]="badgeClass()"><ng-content /></span> `,
  styles: `
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding-inline: 8px;
      border: 1px solid #262626;
      border-radius: 9999px;
      background-color: #1f1f1f;
      color: #a3a3a3;
      font-size: var(--text-caption);
      font-weight: 550;
      line-height: 1;
      white-space: nowrap;
    }

    .badge--info {
      border-color: #404040;
      background-color: #141414;
      color: #a3a3a3;
    }

    .badge--success {
      border-color: #404040;
      background-color: transparent;
      color: #fafafa;
    }

    .badge--warning {
      border-color: #8a8a8a;
      border-style: dashed;
      background-color: #1f1f1f;
      color: #fafafa;
    }

    .badge--danger {
      border-color: #fafafa;
      background-color: #fafafa;
      color: #0a0a0a;
    }
  `,
})
export class BadgeComponent {
  readonly tone = input<BadgeTone>('neutral');

  protected readonly badgeClass = computed(() => `badge badge--${this.tone()}`);
}
