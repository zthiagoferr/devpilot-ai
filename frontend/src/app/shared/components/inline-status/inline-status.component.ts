import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { IconComponent, IconName } from '../icon/icon.component';

export type InlineStatusTone = 'info' | 'success' | 'warning' | 'error' | 'loading';

const TONE_ICON: Readonly<Record<InlineStatusTone, IconName>> = {
  info: 'info',
  success: 'check',
  warning: 'alertTriangle',
  error: 'xCircle',
  loading: 'clock',
};

/**
 * Inline feedback block that mirrors the visual state with a live region, so
 * the same message is available to sighted and assistive-technology users.
 */
@Component({
  selector: 'app-inline-status',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div
      [class]="statusClass()"
      [attr.role]="tone() === 'error' ? 'alert' : 'status'"
      [attr.aria-live]="tone() === 'error' ? 'assertive' : 'polite'"
      aria-atomic="true"
    >
      <span class="status__icon">
        <app-icon [name]="icon()" [size]="18" [strokeWidth]="2" />
      </span>
      <div class="status__content">
        <p class="status__message">{{ message() }}</p>
        <ng-content />
      </div>
    </div>
  `,
  styles: `
    .status {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 14px;
      border: 1px solid #262626;
      border-radius: var(--radius-md);
      background-color: #080808;
      color: #a3a3a3;
      font-size: var(--text-body-sm);
    }

    .status__icon {
      display: inline-flex;
      margin-block-start: 2px;
      color: #a3a3a3;
    }

    .status__content {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
    }

    .status__message {
      color: var(--color-text);
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    .status--success {
      border-color: #404040;
      background-color: #080808;
    }

    .status--success .status__icon {
      color: #fafafa;
    }

    .status--warning {
      border-color: #8a8a8a;
      border-style: dashed;
      background-color: #080808;
    }

    .status--warning .status__icon {
      color: #a3a3a3;
    }

    .status--error {
      border-color: #fafafa;
      background-color: #1f1f1f;
    }

    .status--error .status__icon {
      color: #fafafa;
    }

    .status--loading .status__icon {
      animation: pulse 1.4s var(--ease-ui) infinite;
    }

    @media (prefers-reduced-motion: reduce) {
      .status--loading .status__icon {
        animation: none;
      }
    }

    @keyframes pulse {
      50% {
        opacity: 0.45;
      }
    }
  `,
})
export class InlineStatusComponent {
  readonly tone = input<InlineStatusTone>('info');
  readonly message = input.required<string>();

  protected readonly icon = computed(() => TONE_ICON[this.tone()]);

  protected readonly statusClass = computed(() => `status status--${this.tone()}`);
}
