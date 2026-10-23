import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span [class]="badgeClass()"><ng-content /></span>
  `,
  styles: `
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding-inline: 8px;
      border: 1px solid var(--color-border);
      border-radius: 9999px;
      background-color: var(--color-surface-raised);
      color: var(--color-muted);
      font-size: var(--text-caption);
      font-weight: 550;
      line-height: 1;
      white-space: nowrap;
    }

    .badge--info {
      border-color: color-mix(in oklab, var(--color-accent) 40%, transparent);
      background-color: color-mix(in oklab, var(--color-accent) 12%, var(--color-surface));
      color: var(--color-accent);
    }

    .badge--success {
      border-color: color-mix(in oklab, var(--color-success) 40%, transparent);
      background-color: color-mix(in oklab, var(--color-success) 12%, var(--color-surface));
      color: var(--color-success);
    }

    .badge--warning {
      border-color: color-mix(in oklab, var(--color-warning) 40%, transparent);
      background-color: color-mix(in oklab, var(--color-warning) 12%, var(--color-surface));
      color: var(--color-warning);
    }

    .badge--danger {
      border-color: color-mix(in oklab, var(--color-danger) 40%, transparent);
      background-color: color-mix(in oklab, var(--color-danger) 12%, var(--color-surface));
      color: var(--color-danger);
    }
  `,
})
export class BadgeComponent {
  readonly tone = input<BadgeTone>('neutral');

  protected readonly badgeClass = computed(() => `badge badge--${this.tone()}`);
}
