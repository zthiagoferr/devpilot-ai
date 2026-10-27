import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { IconComponent } from '../icon/icon.component';

/**
 * Presentational label/hint/error shell for a single form control.
 * The projected control owns the `aria-describedby` wiring through the
 * `controlId` supplied here.
 */
@Component({
  selector: 'app-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="field">
      <label class="field__label" [for]="controlId()">
        {{ label() }}
        @if (required()) {
          <span class="field__required" aria-hidden="true">*</span>
          <span class="sr-only"> (obrigatório)</span>
        }
      </label>

      <ng-content />

      @if (hint() && !error()) {
        <p class="field__hint" [id]="hintId()">{{ hint() }}</p>
      }

      @if (error()) {
        <p class="field__error" [id]="errorId()" role="alert">
          <app-icon name="alertTriangle" [size]="14" [strokeWidth]="2" />
          <span>{{ error() }}</span>
        </p>
      }
    </div>
  `,
  styles: `
    .field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }

    .field__label {
      display: inline-flex;
      align-items: baseline;
      gap: 4px;
      color: #a3a3a3;
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 550;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .field__required {
      color: #fafafa;
    }

    .field__hint {
      color: #8a8a8a;
      font-size: var(--text-caption);
    }

    .field__error {
      display: flex;
      align-items: flex-start;
      gap: 6px;
      color: #fafafa;
      font-size: var(--text-caption);
    }

    .field__error app-icon {
      margin-block-start: 2px;
    }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
  `,
})
export class FieldComponent {
  readonly label = input.required<string>();
  readonly controlId = input.required<string>();
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);

  protected readonly hintId = computed(() => `${this.controlId()}-hint`);
  protected readonly errorId = computed(() => `${this.controlId()}-error`);
}
