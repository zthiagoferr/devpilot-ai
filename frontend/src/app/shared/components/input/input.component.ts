import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';

import { createFieldId } from '../field/field-id';
import { FieldComponent } from '../field/field.component';

export type InputType = 'text' | 'url' | 'search' | 'email' | 'password';

@Component({
  selector: 'app-input',
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
      <input
        class="field-control"
        [id]="controlId()"
        [type]="type()"
        [name]="name()"
        [value]="value()"
        [attr.placeholder]="placeholder() || null"
        [attr.autocomplete]="autocomplete() || null"
        [attr.autocapitalize]="capitalize()"
        [attr.spellcheck]="spellcheck()"
        [attr.maxlength]="maxlength() ?? null"
        [attr.aria-invalid]="error() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="required() ? 'true' : null"
        (input)="updateValue($event)"
        (blur)="blurred.emit()"
      />
    </app-field>
  `,
})
export class InputComponent {
  readonly label = input.required<string>();
  readonly value = model('');
  readonly controlId = input(createFieldId('input'));
  readonly type = input<InputType>('text');
  readonly name = input('');
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);
  readonly placeholder = input('');
  readonly autocomplete = input('');
  readonly maxlength = input<number | null>(null);
  readonly spellcheck = input(false);
  readonly capitalize = input('off');

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
    this.value.set((event.target as HTMLInputElement).value);
  }
}
