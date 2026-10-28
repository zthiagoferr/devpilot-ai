import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md';

@Component({
  selector: 'app-button',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class.is-block]': 'fullWidth()',
  },
  template: `
    <button
      [type]="type()"
      [class]="buttonClass()"
      [disabled]="disabled() || loading()"
      [attr.aria-busy]="loading() ? 'true' : null"
      [attr.aria-label]="ariaLabel() || null"
      [attr.aria-expanded]="ariaExpanded() === null ? null : ariaExpanded() ? 'true' : 'false'"
      [attr.aria-controls]="ariaControls() || null"
    >
      @if (loading()) {
        <span class="spinner" aria-hidden="true"></span>
      }
      <span class="button-label"><ng-content /></span>
    </button>
  `,
  styles: `
    :host {
      display: inline-flex;
      max-width: 100%;
    }

    :host(.is-block) {
      display: flex;
      width: 100%;
    }

    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      width: 100%;
      min-height: 44px;
      padding-inline: 16px;
      border: 1px solid transparent;
      border-radius: var(--radius-md);
      background-color: transparent;
      color: var(--color-text);
      font-size: var(--text-body-sm);
      font-weight: 550;
      line-height: 1;
      letter-spacing: -0.005em;
      text-decoration: none;
      cursor: pointer;
      user-select: none;
      transition:
        background-color 150ms var(--ease-ui),
        border-color 150ms var(--ease-ui),
        color 150ms var(--ease-ui),
        box-shadow 150ms var(--ease-ui),
        transform 120ms var(--ease-ui);
    }

    .button--sm {
      min-height: 36px;
      padding-inline: 12px;
      font-size: var(--text-caption);
    }

    .button--primary {
      background-color: #fafafa;
      color: var(--color-on-primary);
      box-shadow: 0 10px 28px -16px rgb(0 0 0 / 0.9);
    }

    .button--secondary {
      background-color: #1f1f1f;
      border-color: #333333;
      color: #fafafa;
    }

    .button--ghost {
      color: #a3a3a3;
    }

    .button--danger {
      background-color: transparent;
      border-color: #4d4d4d;
      color: #fafafa;
    }

    .button:focus-visible {
      outline: 2px solid #fafafa;
      outline-offset: 3px;
      box-shadow: 0 0 0 4px rgb(250 250 250 / 0.18);
    }

    .button:active:not(:disabled) {
      transform: scale(0.98);
    }

    .button:disabled {
      background-color: #1f1f1f;
      border-color: #262626;
      color: #a3a3a3;
      box-shadow: none;
      cursor: not-allowed;
    }

    .button--ghost:disabled {
      background-color: #1f1f1f;
    }

    @media (hover: hover) {
      .button--primary:hover:not(:disabled) {
        background-color: #e5e5e5;
      }

      .button--secondary:hover:not(:disabled) {
        background-color: #262626;
        border-color: #666666;
      }

      .button--ghost:hover:not(:disabled) {
        background-color: #1f1f1f;
        color: #fafafa;
      }

      .button--danger:hover:not(:disabled) {
        border-color: #fafafa;
        background-color: #1f1f1f;
      }
    }

    @media (max-width: 767px) {
      .button--sm {
        min-height: 44px;
      }
    }

    .spinner {
      width: 14px;
      height: 14px;
      flex: none;
      border: 2px solid currentColor;
      border-block-start-color: transparent;
      border-radius: 9999px;
      animation: spin 700ms linear infinite;
    }

    .button-label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class ButtonComponent {
  readonly variant = input<ButtonVariant>('primary');
  readonly size = input<ButtonSize>('md');
  readonly type = input<'button' | 'submit' | 'reset'>('button');
  readonly loading = input(false);
  readonly disabled = input(false);
  readonly fullWidth = input(false);
  readonly ariaLabel = input('');
  readonly ariaExpanded = input<boolean | null>(null);
  readonly ariaControls = input('');

  protected readonly buttonClass = computed(
    () => `button button--${this.variant()} button--${this.size()}`,
  );
}
