import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';

import { AnalysisLanguage } from '../../../core/api/api.types';
import { InputComponent } from '../input/input.component';
import { SelectComponent } from '../select/select.component';
import { LANGUAGE_OPTIONS } from './language-options';

/**
 * Language selector shared by both analysis modes.
 *
 * `auto` keeps the backend detection; picking a language is an explicit
 * override. The Protheus version only appears for ADVPL and is optional: the
 * AI analysis does not need a local Protheus installation.
 */
@Component({
  selector: 'app-language-select',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InputComponent, SelectComponent],
  template: `
    <div class="language-select">
      <app-select
        label="Linguagem"
        hint="Detecção automática considera a extensão do arquivo e o conteúdo."
        [options]="options"
        [value]="value()"
        (valueChange)="updateLanguage($event)"
      />

      @if (isAdvpl()) {
        <app-input
          label="Versão Protheus"
          placeholder="Ex.: 12.1.2410"
          hint="Opcional. A análise por IA não exige Protheus instalado."
          autocomplete="off"
          [maxlength]="50"
          [value]="protheusVersion()"
          (valueChange)="protheusVersion.set($event)"
        />
      }
    </div>
  `,
  styles: `
    .language-select {
      display: grid;
      gap: 16px;
    }

    @media (min-width: 768px) {
      .language-select {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: start;
      }
    }
  `,
})
export class LanguageSelectComponent {
  readonly value = model<AnalysisLanguage>('auto');
  readonly protheusVersion = model('');

  protected readonly options = LANGUAGE_OPTIONS;
  protected readonly isAdvpl = computed(() => this.value() === 'advpl');

  protected updateLanguage(value: string): void {
    if (isAnalysisLanguage(value)) {
      this.value.set(value);
    }
  }
}

function isAnalysisLanguage(value: string): value is AnalysisLanguage {
  return LANGUAGE_OPTIONS.some((option) => option.value === value);
}
