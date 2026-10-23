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
      background-color: var(--color-primary);
      color: var(--color-text);
      box-shadow: 0 10px 28px -16px rgb(37 99 235 / 0.9);
    }

    .button--secondary {
      background-color: var(--color-surface-raised);
      border-color: var(--color-border);
      color: var(--color-text);
    }

    .button--ghost {
      color: var(--color-muted);
    }

    .button--danger {
      background-color: var(--color-surface-raised);
      border-color: color-mix(in oklab, var(--color-danger) 42%, transparent);
      color: var(--color-danger);
    }

    .button:focus-visible {
      outline: 2px solid var(--color-accent);
      outline-offset: 2px;
      box-shadow: 0 0 0 4px rgb(37 99 235 / 0.25);
    }

    .button:active:not(:disabled) {
      transform: scale(0.98);
    }

    .button:disabled {
      background-color: var(--color-surface-raised);
      border-color: var(--color-border-soft);
      color: var(--color-muted);
      box-shadow: none;
      cursor: not-allowed;
    }

    .button--ghost:disabled {
      background-color: transparent;
    }

    @media (hover: hover) {
      .button--primary:hover:not(:disabled) {
        background-color: color-mix(in oklab, var(--color-primary) 86%, #000);
      }

      .button--secondary:hover:not(:disabled) {
        background-color: color-mix(in oklab, var(--color-surface-raised) 82%, var(--color-border));
        border-color: var(--color-accent);
      }

      .button--ghost:hover:not(:disabled) {
        background-color: var(--color-surface-raised);
        color: var(--color-text);
      }

      .button--danger:hover:not(:disabled) {
        background-color: color-mix(in oklab, var(--color-danger) 14%, var(--color-surface));
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

  protected readonly buttonClass = computed(
    () => `button button--${this.variant()} button--${this.size()}`,
  );
}
