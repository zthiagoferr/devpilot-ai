import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { Analysis, Correction } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { LoginPromptService } from '../../../core/auth/login-prompt.service';
import { AnalysisNewComponent } from './analysis-new.component';

const ADVPL_ANALYSIS: Analysis = {
  id: 'analysis-1',
  task: 'code_analysis',
  project_name: 'Financeiro',
  source_code: 'User Function Teste()\nIf .T.\nReturn\n',
  repository_url: null,
  result: {
    score: 70,
    summary: 'Um problema encontrado.',
    language: 'advpl',
    language_source: 'manual',
    confidence: 1,
    issues: [
      {
        severity: 'high',
        message: 'Bloco IF sem fechamento',
        line: 2,
        column: 4,
        cause: 'unclosed_block',
        code: 'unclosed_block',
        language: 'advpl',
        origin: 'validator',
        analysis_kind: 'heuristic_validation',
      },
    ],
  },
  status: 'completed',
  created_at: '2026-10-28T12:00:00Z',
};

const REPOSITORY_ANALYSIS: Analysis = {
  id: 'analysis-2',
  task: 'code',
  project_name: 'Repositório',
  source_code: 'print(2)',
  repository_url: 'owner/repo',
  result: {
    score: 82,
    summary: 'Um problema no repositório.',
    language: 'python',
    confidence: 1,
    issues: [
      {
        severity: 'medium',
        message: 'Outro problema no repositório',
        line: 1,
        cause: 'unused_import',
        code: 'unused_import',
        language: 'python',
        origin: 'validator',
        analysis_kind: 'heuristic_validation',
      },
    ],
  },
  status: 'completed',
  created_at: '2026-10-28T12:05:00Z',
};

const CORRECTION: Correction = {
  id: 'correction-1',
  analysis_id: 'analysis-1',
  language: 'advpl',
  file: null,
  issue_ref: 'Bloco IF sem fechamento',
  original_code: 'User Function Teste()\nIf .T.\nReturn\n',
  corrected_code: 'User Function Teste()\nIf .T.\nReturn\nEndIf\n',
  diff: '--- a\n+++ b\n@@ -1,3 +1,4 @@\n User Function Teste()\n If .T.\n Return\n+EndIf\n',
  explanation: 'Faltava o EndIf.',
  origin: 'ai',
  post_validation: {
    status: 'passed',
    target_resolved: true,
    issues: [],
    summary: 'Resolvido.',
  },
  status: 'pending',
  model: 'fake',
  protheus_version: null,
  created_at: '2026-10-28T12:10:00Z',
  decided_at: null,
};

describe('AnalysisNewComponent', () => {
  const createAnalysis = vi.fn();
  const createCorrection = vi.fn();
  const loginOpen = vi.fn();

  beforeEach(async () => {
    createAnalysis.mockReset();
    createCorrection.mockReset();
    loginOpen.mockReset();
    createAnalysis.mockResolvedValue(ADVPL_ANALYSIS);
    createCorrection.mockResolvedValue(CORRECTION);

    await TestBed.configureTestingModule({
      imports: [AnalysisNewComponent],
      providers: [
        provideRouter([]),
        { provide: ApiClient, useValue: { createAnalysis, createCorrection } },
        { provide: AuthService, useValue: { isAuthenticated: () => false } },
        { provide: LoginPromptService, useValue: { open: loginOpen } },
      ],
    }).compileComponents();
  });

  async function settle(fixture: ComponentFixture<AnalysisNewComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function inputByLabel(element: HTMLElement, label: string): HTMLInputElement {
    const labels = Array.from(element.querySelectorAll('label'));
    const match = labels.find((item) => (item.textContent ?? '').includes(label));
    const id = match?.getAttribute('for');
    const input = id ? element.querySelector<HTMLInputElement>(`#${id}`) : null;
    if (input === null) {
      throw new Error(`Input for ${label} not found`);
    }
    return input;
  }

  function textareaByLabel(element: HTMLElement, label: string): HTMLTextAreaElement {
    const labels = Array.from(element.querySelectorAll('label'));
    const match = labels.find((item) => (item.textContent ?? '').includes(label));
    const id = match?.getAttribute('for');
    const textarea = id ? element.querySelector<HTMLTextAreaElement>(`#${id}`) : null;
    if (textarea === null) {
      throw new Error(`Textarea for ${label} not found`);
    }
    return textarea;
  }

  function type(input: HTMLInputElement | HTMLTextAreaElement, value: string): void {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  it('submits the ADVPL override and the optional Protheus version', async () => {
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Financeiro');
    type(textareaByLabel(element, 'Código-fonte'), 'User Function Teste()\nIf .T.\nReturn\n');

    const language = element.querySelector<HTMLSelectElement>('select');
    if (language !== null) {
      language.value = 'advpl';
      language.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    type(inputByLabel(element, 'Versão Protheus'), '12.1.2410');

    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(createAnalysis).toHaveBeenCalledWith(
      {
        task: 'code_analysis',
        project_name: 'Financeiro',
        source_code: 'User Function Teste()\nIf .T.\nReturn\n',
        language: 'advpl',
        protheus_version: '12.1.2410',
      },
      expect.any(AbortSignal),
    );

    expect(element.textContent).toContain('ADVPL');
    expect(element.textContent).toContain('Causa: Bloco sem fechamento');
    expect(element.textContent).toContain('Validação local (heurística)');
    expect(element.textContent).toContain('Análise estática — não valida compilação');
    expect(element.textContent).toContain('Corrigir com IA');
  });

  it('uses auto detection by default and never sends a Protheus version', async () => {
    createAnalysis.mockResolvedValue({
      ...ADVPL_ANALYSIS,
      result: { score: 100, summary: 'ok', language: 'python', confidence: 0.9, issues: [] },
    });
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Sample');
    type(textareaByLabel(element, 'Código-fonte'), 'print(1)');

    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(createAnalysis).toHaveBeenCalledWith(
      {
        task: 'code_analysis',
        project_name: 'Sample',
        source_code: 'print(1)',
        language: 'auto',
      },
      expect.any(AbortSignal),
    );
    expect(element.textContent).toContain('Python');
    expect(element.textContent).toContain('90% de confiança');
  });

  it('keeps each result scoped to its tab without duplicating requests', async () => {
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Sample');
    type(textareaByLabel(element, 'Código-fonte'), 'print(1)');
    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(createAnalysis).toHaveBeenCalledTimes(1);
    expect(element.textContent).toContain('Resultado da análise');

    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[1]?.click();
    fixture.detectChanges();

    // The repository tab starts empty and does not show the paste result.
    expect(element.textContent).not.toContain('Resultado da análise');
    expect(element.textContent).toContain('Repositório GitHub');

    tabs[0]?.click();
    fixture.detectChanges();

    expect(element.textContent).toContain('Resultado da análise');
    expect(createAnalysis).toHaveBeenCalledTimes(1);
  });

  it('does not leak an open correction panel across analysis tabs', async () => {
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Financeiro');
    type(textareaByLabel(element, 'Código-fonte'), 'User Function Teste()\nIf .T.\nReturn\n');
    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    const toggleButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Corrigir com IA'),
    );
    toggleButton?.click();
    fixture.detectChanges();
    await settle(fixture);

    // The list button expands the panel; the panel then requests the correction.
    const correctButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Corrigir com IA'),
    );
    correctButton?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Código corrigido');
    expect(element.textContent).toContain('Faltava o EndIf.');

    fixture.componentInstance['handleRepositoryResult'](REPOSITORY_ANALYSIS);
    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[1]?.click();
    fixture.detectChanges();
    await settle(fixture);

    // The repository issue is shown, but the ADVPL correction (and the open
    // panel state) must not survive the tab switch.
    expect(element.textContent).toContain('Outro problema no repositório');
    expect(element.textContent).not.toContain('Código corrigido');
    expect(element.textContent).not.toContain('Faltava o EndIf.');
    expect(
      Array.from(element.querySelectorAll('button')).some((button) =>
        (button.textContent ?? '').includes('Ocultar correção'),
      ),
    ).toBe(false);
  });

  it('shows "Não avaliado" instead of 100/100 when validation was skipped', async () => {
    createAnalysis.mockResolvedValue({
      ...ADVPL_ANALYSIS,
      result: {
        score: 100,
        summary: 'Language detection did not select a structural validator.',
        language: 'unknown',
        language_source: 'fallback',
        confidence: 0,
        issues: [
          {
            severity: 'info',
            message: 'Language could not be detected from the file path or content.',
            cause: 'language_undetected',
            language: 'unknown',
            origin: 'validator',
            analysis_kind: 'heuristic_validation',
          },
        ],
        validation_skipped: true,
      },
    });
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Desconhecido');
    type(textareaByLabel(element, 'Código-fonte'), 'prose without code markers');
    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(element.textContent).toContain('Não avaliado');
    expect(element.textContent).toContain('Idioma não reconhecido — selecione manualmente.');
    expect(element.textContent).not.toContain('100/100');
  });

  it('does not show the repository result on the paste tab', async () => {
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    fixture.componentInstance['handleRepositoryResult'](REPOSITORY_ANALYSIS);
    const tabs = element.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs[1]?.click();
    fixture.detectChanges();

    expect(element.textContent).toContain('Resultado da análise');
    expect(element.textContent).toContain('Outro problema no repositório');

    tabs[0]?.click();
    fixture.detectChanges();

    expect(element.textContent).not.toContain('Resultado da análise');
    expect(element.textContent).not.toContain('Outro problema no repositório');
    expect(createAnalysis).not.toHaveBeenCalled();
  });

  it('shows partial coverage and the caveat for a low-confidence detection', async () => {
    createAnalysis.mockResolvedValue({
      ...ADVPL_ANALYSIS,
      result: {
        ...ADVPL_ANALYSIS.result,
        score: 90,
        score_status: 'partial',
        coverage: {
          advpl: {
            score_status: 'partial',
            checks: ['structure', 'preprocessor'],
            limitations: ['No runtime or semantic analysis'],
          },
        },
      },
    });
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Parcial');
    type(textareaByLabel(element, 'Código-fonte'), 'If .T.\n');
    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(element.textContent).toContain('Análise parcial — confirme a linguagem manualmente.');
    expect(element.textContent).toContain('Cobertura da análise');
    expect(element.textContent).toContain('Pré-processador');
    expect(element.textContent).toContain('Sem análise de execução ou semântica');
  });

  it('marks the score as unavailable when the validator failed', async () => {
    createAnalysis.mockResolvedValue({
      ...ADVPL_ANALYSIS,
      result: {
        ...ADVPL_ANALYSIS.result,
        score: 90,
        score_status: 'unavailable',
        summary: 'Structural validation could not be completed.',
      },
    });
    const fixture = TestBed.createComponent(AnalysisNewComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    type(inputByLabel(element, 'Nome do projeto'), 'Falha');
    type(textareaByLabel(element, 'Código-fonte'), 'If .T.\n');
    element
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle(fixture);

    expect(element.textContent).toContain('Validação indisponível');
    expect(element.textContent).not.toContain('90/100');
  });
});
