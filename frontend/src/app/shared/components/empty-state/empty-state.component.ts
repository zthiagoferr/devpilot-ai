import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { IconComponent, IconName } from '../icon/icon.component';

@Component({
  selector: 'app-empty-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="empty">
      <span class="empty__icon" aria-hidden="true">
        <app-icon [name]="icon()" [size]="24" [strokeWidth]="1.75" />
      </span>
      <h3 class="empty__title">{{ title() }}</h3>
      @if (description()) {
        <p class="empty__description">{{ description() }}</p>
      }
      <div class="empty__actions">
        <ng-content />
      </div>
    </div>
  `,
  styles: `
    .empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      padding: 40px 24px;
      text-align: center;
      border: 1px dashed var(--color-border);
      border-radius: var(--radius-lg);
      background-color: color-mix(in oklab, var(--color-surface-sunken) 70%, transparent);
    }

    .empty__icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      margin-block-end: 4px;
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      background-color: var(--color-surface-raised);
      color: var(--color-accent);
    }

    .empty__title {
      color: var(--color-text);
      font-size: var(--text-heading);
    }

    .empty__description {
      max-width: 48ch;
      color: var(--color-muted);
      font-size: var(--text-body-sm);
      line-height: 1.55;
    }

    .empty__actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 8px;
      margin-block-start: 8px;
    }

    .empty__actions:empty {
      display: none;
    }
  `,
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly description = input('');
  readonly icon = input<IconName>('sparkles');
}
