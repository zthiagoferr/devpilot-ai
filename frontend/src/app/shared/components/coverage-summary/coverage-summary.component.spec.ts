import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { AnalysisCoverage } from '../../../core/api/api.types';
import { CoverageSummaryComponent } from './coverage-summary.component';

describe('CoverageSummaryComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CoverageSummaryComponent],
    }).compileComponents();
  });

  async function render(
    coverage: Readonly<Record<string, AnalysisCoverage>> | null | undefined,
  ): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(CoverageSummaryComponent);
    fixture.componentRef.setInput('coverage', coverage);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('renders each language with its translated checks and limitations', async () => {
    const element = await render({
      advpl: {
        score_status: 'evaluated',
        checks: ['structure', 'preprocessor'],
        limitations: ['No runtime or semantic analysis'],
      },
      python: {
        score_status: 'evaluated',
        checks: ['syntax'],
        limitations: [],
      },
    });

    const text = element.textContent ?? '';
    expect(text).toContain('Cobertura da análise');
    expect(text).toContain('O que foi verificado');
    expect(text).toContain('O que não é coberto');

    expect(text).toContain('ADVPL');
    expect(text).toContain('Estrutura');
    expect(text).toContain('Pré-processador');
    expect(text).toContain('Sem análise de execução ou semântica');

    expect(text).toContain('Python');
    expect(text).toContain('Sintaxe');
  });

  it('renders nothing for missing or empty coverage', async () => {
    const nullElement = await render(null);
    expect(nullElement.textContent).not.toContain('Cobertura da análise');

    const undefinedElement = await render(undefined);
    expect(undefinedElement.textContent).not.toContain('Cobertura da análise');

    const emptyElement = await render({});
    expect(emptyElement.textContent).not.toContain('Cobertura da análise');

    const withoutDetailsElement = await render({
      python: { checks: [], limitations: [] },
    });
    expect(withoutDetailsElement.textContent).not.toContain('Cobertura da análise');
  });

  it('falls back to the raw value when a language, check or limitation is unknown', async () => {
    const element = await render({
      ruby: {
        score_status: 'partial',
        checks: ['custom_check'],
        limitations: ['Unknown limitation phrase'],
      },
    });

    const text = element.textContent ?? '';
    expect(text).toContain('ruby');
    expect(text).toContain('custom_check');
    expect(text).toContain('Unknown limitation phrase');
  });
});
