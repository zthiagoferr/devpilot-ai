import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { ButtonComponent } from '../button/button.component';
import { IconComponent } from '../icon/icon.component';

@Component({
  selector: 'app-error-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent],
  template: `
    <div class="error" role="alert">
      <span class="error__icon" aria-hidden="true">
        <app-icon name="alertTriangle" [size]="24" [strokeWidth]="1.75" />
      </span>
      <h3 class="error__title">{{ title() }}</h3>
      <p class="error__description">{{ description() }}</p>
      <div class="error__actions">
        @if (showRetry()) {
          <app-button variant="secondary" (click)="retry.emit()">Tentar novamente</app-button>
        }
        <ng-content />
      </div>
    </div>
  `,
  styles: `
    .error {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
      padding: 24px;
      border: 1px solid color-mix(in oklab, var(--color-danger) 32%, transparent);
      border-radius: var(--radius-lg);
      background-color: color-mix(in oklab, var(--color-danger) 7%, var(--color-surface));
    }

    .error__icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border: 1px solid color-mix(in oklab, var(--color-danger) 40%, transparent);
      border-radius: var(--radius-md);
      background-color: color-mix(in oklab, var(--color-danger) 10%, var(--color-surface));
      color: var(--color-danger);
    }

    .error__title {
      color: var(--color-text);
      font-size: var(--text-heading);
    }

    .error__description {
      max-width: 62ch;
      color: var(--color-muted);
      font-size: var(--text-body-sm);
      line-height: 1.55;
    }

    .error__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-block-start: 8px;
    }

    .error__actions:empty {
      display: none;
    }
  `,
})
export class ErrorStateComponent {
  readonly title = input.required<string>();
  readonly description = input.required<string>();
  readonly showRetry = input(true);

  readonly retry = output<void>();
}
