import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { AnalysisCoverage } from '../../../core/api/api.types';
import {
  coverageCheckLabel,
  coverageLimitationLabel,
} from '../../utils/pt-br-messages';
import { languageLabel } from '../language-select/language-options';

interface CoverageEntryView {
  readonly language: string;
  readonly label: string;
  readonly checks: readonly string[];
  readonly limitations: readonly string[];
}

/**
 * Shows what each deterministic validator checked and what it explicitly does
 * not cover. It renders nothing for legacy payloads without coverage, so the
 * historical result panels stay unchanged.
 */
@Component({
  selector: 'app-coverage-summary',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (entries().length > 0) {
      <section class="flex flex-col gap-4" aria-label="Cobertura da análise">
        <h2 class="text-heading font-semibold text-text">Cobertura da análise</h2>

        @for (entry of entries(); track entry.language) {
          <div class="flex flex-col gap-3">
            <h3 class="text-body-sm font-semibold text-text">{{ entry.label }}</h3>

            <div class="grid gap-4 sm:grid-cols-2">
              @if (entry.checks.length > 0) {
                <div>
                  <p class="text-caption font-medium text-text">O que foi verificado</p>
                  <ul class="mt-1 flex flex-col gap-1">
                    @for (check of entry.checks; track check) {
                      <li class="flex items-start gap-2 text-body-sm text-muted">
                        <span class="text-subtle" aria-hidden="true">•</span>
                        <span>{{ check }}</span>
                      </li>
                    }
                  </ul>
                </div>
              }

              @if (entry.limitations.length > 0) {
                <div>
                  <p class="text-caption font-medium text-text">O que não é coberto</p>
                  <ul class="mt-1 flex flex-col gap-1">
                    @for (limitation of entry.limitations; track limitation) {
                      <li class="flex items-start gap-2 text-body-sm text-muted">
                        <span class="text-subtle" aria-hidden="true">•</span>
                        <span>{{ limitation }}</span>
                      </li>
                    }
                  </ul>
                </div>
              }
            </div>
          </div>
        }
      </section>
    }
  `,
})
export class CoverageSummaryComponent {
  readonly coverage = input<
    Readonly<Record<string, AnalysisCoverage>> | null | undefined
  >(null);

  protected readonly entries = computed<readonly CoverageEntryView[]>(() => {
    const coverage = this.coverage();
    if (coverage === null || coverage === undefined) {
      return [];
    }
    return Object.entries(coverage)
      .map(([language, entry]) => ({
        language,
        label: languageLabel(language),
        checks: (entry.checks ?? []).map(coverageCheckLabel),
        limitations: (entry.limitations ?? []).map(coverageLimitationLabel),
      }))
      .filter((entry) => entry.checks.length > 0 || entry.limitations.length > 0);
  });
}
