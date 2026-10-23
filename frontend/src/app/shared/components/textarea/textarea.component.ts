import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';

import { createFieldId } from '../field/field-id';
import { FieldComponent } from '../field/field.component';

@Component({
  selector: 'app-textarea',
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
      <textarea
        class="field-control field-control--code"
        [id]="controlId()"
        [name]="name()"
        [rows]="rows()"
        [value]="value()"
        [attr.placeholder]="placeholder() || null"
        [attr.autocomplete]="autocomplete() || null"
        [attr.maxlength]="maxlength() ?? null"
        [attr.aria-invalid]="error() ? 'true' : null"
        [attr.aria-describedby]="describedBy()"
        [attr.aria-required]="required() ? 'true' : null"
        (input)="updateValue($event)"
        (blur)="blurred.emit()"
      ></textarea>
    </app-field>
  `,
})
export class TextareaComponent {
  readonly label = input.required<string>();
  readonly value = model('');
  readonly controlId = input(createFieldId('textarea'));
  readonly name = input('');
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);
  readonly rows = input(10);
  readonly placeholder = input('');
  readonly autocomplete = input('');
  readonly maxlength = input<number | null>(null);

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
    this.value.set((event.target as HTMLTextAreaElement).value);
  }
}
