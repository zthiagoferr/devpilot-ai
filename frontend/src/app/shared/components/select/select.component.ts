import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';

import { createFieldId } from '../field/field-id';
import { FieldComponent } from '../field/field.component';

export interface SelectOption {
  readonly value: string;
  readonly label: string;
}

@Component({
  selector: 'app-select',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FieldComponent],
  template: `
    <app-field
      [label]="label()"
      [controlId]="controlId()"
      [hint]="hint()"
      [error]="error()"
      [required]="required()"
    >
      <select
        class="field-control"
        [id]="controlId()"
        [name]="name()"
        [value]="value()"
        [attr.aria-invalid]="error() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="required() ? 'true' : null"
        (change)="updateValue($event)"
        (blur)="blurred.emit()"
      >
        @if (placeholder()) {
          <option value="" disabled>{{ placeholder() }}</option>
        }
        @for (option of options(); track option.value) {
          <option [value]="option.value">{{ option.label }}</option>
        }
      </select>
    </app-field>
  `,
})
export class SelectComponent {
  readonly label = input.required<string>();
  readonly options = input.required<readonly SelectOption[]>();
  readonly value = model('');
  readonly controlId = input(createFieldId('select'));
  readonly name = input('');
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);
  readonly placeholder = input('');

  readonly blurred = output<void>();

  protected readonly describedBy = computed(() => {
    if (this.error()) {
      return `${this.controlId()}-error`;
    }
    if (this.hint()) {
      return `${this.controlId()}-hint`;
    }
    return null;
  });

  protected updateValue(event: Event): void {
    this.value.set((event.target as HTMLSelectElement).value);
  }
}
