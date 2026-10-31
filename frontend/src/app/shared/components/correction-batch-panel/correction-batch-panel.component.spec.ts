import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { ApiError } from '../../../core/api/api-error.mapper';
import {
  Correction,
  CorrectionBatchCreate,
  CorrectionBatchItem,
  CorrectionBatchResponse,
} from '../../../core/api/api.types';
import {
  CorrectionBatchPanelComponent,
  CorrectionBatchSource,
} from './correction-batch-panel.component';

function correction(overrides: Partial<Correction> = {}): Correction {
  return {
    id: 'c1',
    analysis_id: 'analysis-1',
    language: 'python',
    file: 'src/app.py',
    issue_ref: 'print',
    original_code: 'print ("x")\n',
    corrected_code: 'print("x")\n',
    diff: '--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-print ("x")\n+print("x")\n',
    explanation: 'Ajuste de espaçamento.',
    origin: 'ai',
    post_validation: {
      status: 'passed',
      target_resolved: true,
      issues: [],
      summary: 'Problema original resolvido.',
      issues_resolved: [{ message: 'print', severity: 'low', line: 1 }],
      issues_remaining: [],
      issues_new: [],
      issues_warnings: [],
    },
    status: 'pending',
    model: 'fake',
    protheus_version: null,
    created_at: '2026-10-30T12:00:00Z',
    decided_at: null,
    ...overrides,
  };
}

function batch(items: readonly CorrectionBatchItem[]): CorrectionBatchResponse {
  const completed = items.filter((item) => item.status === 'completed').length;
  const failed = items.filter((item) => item.status === 'failed').length;
  const skipped = items.filter((item) => item.status === 'skipped').length;
  return {
    results: items,
    files_total: items.length,
    files_completed: completed,
    files_failed: failed,
    files_skipped: skipped,
    issues_resolved_total: 1,
    issues_remaining_total: 0,
    issues_new_total: 0,
    partial: failed + skipped > 0,
    budget_exceeded: false,
  };
}

const SOURCES: Readonly<Record<string, CorrectionBatchSource>> = {
  'src/app.py': {
    source_code: 'print ("x")\n',
    issues: [{ message: 'print', severity: 'low', line: 1 }],
  },
  'src/util.py': { source_code: 'value = 1\n' },
  'src/broken.py': { source_code: 'def broken(:\n' },
};

describe('CorrectionBatchPanelComponent', () => {
  const decideCorrection = vi.fn();
  const createCorrection = vi.fn();

  beforeEach(async () => {
    decideCorrection.mockReset();
    createCorrection.mockReset();

    await TestBed.configureTestingModule({
      imports: [CorrectionBatchPanelComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: { decideCorrection, createCorrection },
        },
      ],
    }).compileComponents();
  });

  async function settle(fixture: ComponentFixture<CorrectionBatchPanelComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function create(
    payload: CorrectionBatchResponse,
    options: { authenticated?: boolean; analysisId?: string | null } = {},
  ): ComponentFixture<CorrectionBatchPanelComponent> {
    const fixture = TestBed.createComponent(CorrectionBatchPanelComponent);
    fixture.componentRef.setInput('batch', payload);
    fixture.componentRef.setInput('sources', SOURCES);
    fixture.componentRef.setInput('language', 'python');
    fixture.componentRef.setInput('analysisId', options.analysisId ?? 'analysis-1');
    fixture.componentRef.setInput('repositoryContext', {
      paths: ['src/app.py', 'src/util.py', 'src/broken.py'],
      tree_complete: true,
      truncated: false,
    });
    fixture.componentRef.setInput('authenticated', options.authenticated ?? true);
    fixture.detectChanges();
    return fixture;
  }

  function buttonByText(element: HTMLElement, text: string): HTMLButtonElement | undefined {
    return Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes(text),
    );
  }

  function buttonsByText(element: HTMLElement, text: string): HTMLButtonElement[] {
    return Array.from(element.querySelectorAll('button')).filter((button) =>
      (button.textContent ?? '').includes(text),
    );
  }

  it('renders the consolidated summary, statuses and translated reasons', () => {
    const element = create(
      batch([
        { path: 'src/app.py', status: 'completed', correction: correction(), issues_targeted: 1 },
        { path: 'src/util.py', status: 'skipped', issues_targeted: 0, reason: 'no_issues' },
        { path: 'src/broken.py', status: 'failed', issues_targeted: 0, reason: 'not_utf8' },
      ]),
    ).nativeElement as HTMLElement;

    expect(element.textContent).toContain(
      '1 de 3 arquivos concluído · 1 falha · 1 pulado · 1 resolvido · 0 pendentes · 0 novos',
    );
    expect(element.textContent).toContain('src/app.py');
    expect(element.textContent).toContain('Concluído');
    expect(element.textContent).toContain('Pulado');
    expect(element.textContent).toContain('Falhado');
    expect(element.textContent).toContain('sem problemas detectados');
    expect(element.textContent).toContain('arquivo não está em UTF-8 válido');
    expect(element.textContent).toContain('Lote parcial');
  });

  it('shows the budget badge and the translated budget reason', () => {
    const element = create({
      ...batch([{ path: 'src/app.py', status: 'skipped', issues_targeted: 0, reason: 'budget' }]),
      budget_exceeded: true,
    }).nativeElement as HTMLElement;

    expect(element.textContent).toContain('Orçamento esgotado');
    expect(element.textContent).toContain('orçamento de tempo esgotado');
  });

  it('renders one diff and explanation per completed file', () => {
    const element = create(
      batch([
        {
          path: 'src/app.py',
          status: 'completed',
          correction: correction(),
          issues_targeted: 1,
        },
        {
          path: 'src/util.py',
          status: 'completed',
          correction: correction({
            id: 'c2',
            file: 'src/util.py',
            corrected_code: 'value = 2\n',
            diff: '--- a/src/util.py\n+++ b/src/util.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n',
            explanation: 'Valor ajustado.',
          }),
          issues_targeted: 1,
        },
      ]),
    ).nativeElement as HTMLElement;

    expect(element.querySelectorAll('.diff').length).toBe(2);
    expect(element.textContent).toContain('+print("x")');
    expect(element.textContent).toContain('+value = 2');
    expect(element.textContent).toContain('Ajuste de espaçamento.');
    expect(element.textContent).toContain('Valor ajustado.');
  });

  it('approves one file without approving the others, then rejects the other', async () => {
    decideCorrection.mockImplementation(
      async (id: string, decision: { status: 'approved' | 'rejected' }) =>
        correction({
          id,
          file: id === 'c1' ? 'src/app.py' : 'src/util.py',
          status: decision.status,
        }),
    );
    const fixture = create(
      batch([
        { path: 'src/app.py', status: 'completed', correction: correction(), issues_targeted: 1 },
        {
          path: 'src/util.py',
          status: 'completed',
          correction: correction({ id: 'c2', file: 'src/util.py' }),
          issues_targeted: 1,
        },
      ]),
    );
    const element = fixture.nativeElement as HTMLElement;

    const approveButtons = buttonsByText(element, 'Aprovar');
    expect(approveButtons).toHaveLength(2);
    approveButtons[0]?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledTimes(1);
    expect(decideCorrection).toHaveBeenCalledWith('c1', { status: 'approved' });
    let cards = element.querySelectorAll('.batch-item');
    expect(cards[0]?.textContent).toContain('Aprovada');
    expect(cards[1]?.textContent).toContain('Aguardando decisão');
    expect(buttonsByText(cards[1] as HTMLElement, 'Aprovar')).toHaveLength(1);
    expect(cards[1]?.textContent).toContain('A decisão vale apenas para este arquivo');

    const rejectButtons = buttonsByText(element, 'Rejeitar');
    expect(rejectButtons).toHaveLength(1);
    rejectButtons[0]?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledTimes(2);
    expect(decideCorrection).toHaveBeenLastCalledWith('c2', { status: 'rejected' });
    cards = element.querySelectorAll('.batch-item');
    expect(cards[0]?.textContent).toContain('Aprovada');
    expect(cards[1]?.textContent).toContain('Rejeitada');
  });

  it('asks for login instead of deciding when there is no session', async () => {
    const fixture = create(
      batch([
        { path: 'src/app.py', status: 'completed', correction: correction(), issues_targeted: 1 },
      ]),
      { authenticated: false },
    );
    const element = fixture.nativeElement as HTMLElement;
    const loginRequested = vi.fn();
    fixture.componentInstance.loginRequested.subscribe(loginRequested);

    buttonByText(element, 'Entrar')?.click();
    await settle(fixture);

    expect(decideCorrection).not.toHaveBeenCalled();
    expect(loginRequested).toHaveBeenCalledTimes(1);
    expect(element.textContent).toContain(
      'Entre na sua conta para aprovar ou rejeitar as correções.',
    );
  });

  it('retries only the failed file and replaces its result', async () => {
    createCorrection.mockResolvedValue(
      correction({
        id: 'c3',
        file: 'src/broken.py',
        status: 'pending',
        post_validation: {
          status: 'failed',
          target_resolved: false,
          issues: [],
          summary: 'Original issue remains.',
          issues_resolved: [],
          issues_remaining: [{ message: 'sintaxe', severity: 'high', line: 1 }],
          issues_new: [],
          issues_warnings: [],
        },
      }),
    );
    const fixture = create(
      batch([
        { path: 'src/app.py', status: 'completed', correction: correction(), issues_targeted: 1 },
        {
          path: 'src/broken.py',
          status: 'failed',
          issues_targeted: 0,
          reason: 'provider_error',
          error_detail: 'The AI provider could not complete this file.',
        },
      ]),
    );
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent).toContain('Tentar novamente');
    expect(element.textContent).toContain('falha do provedor de IA');
    expect(element.textContent).toContain('The AI provider could not complete this file.');

    buttonByText(element, 'Tentar novamente')?.click();
    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledTimes(1);
    const payload = createCorrection.mock.calls[0]?.[0] as CorrectionBatchCreate;
    expect(payload).toMatchObject({
      analysis_id: 'analysis-1',
      file: 'src/broken.py',
      language: 'python',
      source_code: 'def broken(:\n',
      mode: 'full',
      issues: [],
      repository_context: {
        paths: ['src/app.py', 'src/util.py', 'src/broken.py'],
        tree_complete: true,
        truncated: false,
      },
    });

    const cards = element.querySelectorAll('.batch-item');
    expect(cards[1]?.textContent).toContain('Concluído');
    expect(cards[1]?.textContent).toContain('sintaxe');
    expect(buttonsByText(cards[1] as HTMLElement, 'Tentar novamente')).toHaveLength(0);
    expect(decideCorrection).not.toHaveBeenCalled();
  });

  it('translates a retry failure and keeps the file retryable', async () => {
    createCorrection.mockRejectedValue(
      new ApiError('server', 'AI correction is not configured.', { status: 503 }),
    );
    const fixture = create(
      batch([
        {
          path: 'src/broken.py',
          status: 'failed',
          issues_targeted: 0,
          reason: 'provider_error',
        },
      ]),
    );
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Tentar novamente')?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'A correção de IA não está configurada no servidor. Configure o provedor de LLM.',
    );
    expect(buttonByText(element, 'Tentar novamente')).toBeDefined();
  });
});
