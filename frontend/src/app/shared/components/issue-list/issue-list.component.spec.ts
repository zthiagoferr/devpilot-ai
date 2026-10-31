import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { ApiError } from '../../../core/api/api-error.mapper';
import { AnalysisIssue, Correction } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { IssueListComponent } from './issue-list.component';

const SOURCE = [
  '<!DOCTYPE html>',
  '<html lang="en">',
  '<head><title>Doc</title></head>',
  '<body>',
  '<img src="a.png">',
  '<img src="b.png">',
  '</body>',
  '</html>',
  '',
].join('\n');

const ISSUE_A: AnalysisIssue = {
  message: 'Image is missing an alt attribute.',
  severity: 'medium',
  line: 5,
  cause: 'missing_alt',
  code: 'missing_alt',
  language: 'html',
  origin: 'validator',
  analysis_kind: 'heuristic_validation',
};

const ISSUE_B: AnalysisIssue = {
  message: 'Image is missing an alt attribute.',
  severity: 'medium',
  line: 6,
  cause: 'missing_alt',
  code: 'missing_alt',
  language: 'html',
  origin: 'validator',
  analysis_kind: 'heuristic_validation',
};

const FULL_CORRECTION: Correction = {
  id: 'full-1',
  analysis_id: 'analysis-1',
  language: 'html',
  file: 'index.html',
  issue_ref: 'full:2',
  original_code: SOURCE,
  corrected_code: SOURCE.replace('<img src="a.png">', '<img src="a.png" alt="A">').replace(
    '<img src="b.png">',
    '<img src="b.png" alt="B">',
  ),
  diff: [
    '--- a/index.html',
    '+++ b/index.html',
    '@@ -4,5 +4,5 @@',
    ' <body>',
    '-<img src="a.png">',
    '-<img src="b.png">',
    '+<img src="a.png" alt="A">',
    '+<img src="b.png" alt="B">',
    ' </body>',
    '',
  ].join('\n'),
  explanation: 'Adicionados textos alternativos às duas imagens.',
  origin: 'ai',
  post_validation: {
    status: 'passed',
    target_resolved: true,
    issues: [],
    summary:
      'Local structural validation resolved 2 of 2 target issue(s) and found no relevant new finding. This is a deterministic local check, not an official Protheus validation.',
    issues_resolved: [
      { message: ISSUE_A.message, severity: 'medium', cause: 'missing_alt', line: 5 },
      { message: ISSUE_B.message, severity: 'medium', cause: 'missing_alt', line: 6 },
    ],
    issues_remaining: [],
    issues_new: [],
    issues_warnings: [],
  },
  status: 'pending',
  model: 'fake',
  protheus_version: null,
  created_at: '2026-10-28T12:00:00Z',
  decided_at: null,
};

describe('IssueListComponent (full correction)', () => {
  const createCorrection = vi.fn();
  const decideCorrection = vi.fn();

  beforeEach(async () => {
    createCorrection.mockReset();
    decideCorrection.mockReset();
    createCorrection.mockResolvedValue(FULL_CORRECTION);

    await TestBed.configureTestingModule({
      imports: [IssueListComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: { createCorrection, decideCorrection },
        },
        {
          provide: AuthService,
          useValue: { configured: true, isAuthConfigured: true },
        },
      ],
    }).compileComponents();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function settle(fixture: ComponentFixture<IssueListComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function create(): ComponentFixture<IssueListComponent> {
    const fixture = TestBed.createComponent(IssueListComponent);
    fixture.componentRef.setInput('issues', [ISSUE_A, ISSUE_B]);
    fixture.componentRef.setInput('source', SOURCE);
    fixture.componentRef.setInput('language', 'html');
    fixture.componentRef.setInput('file', 'index.html');
    fixture.componentRef.setInput('analysisId', 'analysis-1');
    fixture.componentRef.setInput('authenticated', true);
    fixture.detectChanges();
    return fixture;
  }

  function buttons(element: HTMLElement, text: string): HTMLButtonElement[] {
    return Array.from(element.querySelectorAll('button')).filter((button) =>
      (button.textContent ?? '').includes(text),
    );
  }

  it('shows a single bulk action with the number of issues', () => {
    const element = create().nativeElement as HTMLElement;

    expect(buttons(element, 'Corrigir todos com IA (2)')).toHaveLength(1);
    expect(element.textContent).toContain('Corrija todos os problemas deste arquivo');
    // The per-issue actions remain untouched.
    expect(buttons(element, 'Corrigir com IA')).toHaveLength(2);
  });

  it('disables the bulk action while the full request is in flight', async () => {
    let resolveCorrection: (value: Correction) => void = () => undefined;
    createCorrection.mockReturnValue(
      new Promise<Correction>((resolve) => {
        resolveCorrection = resolve;
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    fixture.detectChanges();
    await settle(fixture);

    const bulk = buttons(element, 'Corrigir todos com IA (2)')[0];
    expect(bulk?.disabled).toBe(true);
    expect(bulk?.getAttribute('aria-busy')).toBe('true');

    resolveCorrection(FULL_CORRECTION);
    await settle(fixture);

    expect(buttons(element, 'Corrigir todos com IA (2)')[0]?.disabled).toBe(false);
    expect(element.textContent).toContain('Código corrigido');
    expect(element.textContent).toContain('Adicionados textos alternativos às duas imagens.');
    expect(element.textContent).toContain('2 de 2 resolvidos');
    expect(element.querySelector('.diff__line--add')).not.toBeNull();
  });

  it('sends every issue in one full request and never duplicates the action', async () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledTimes(1);
    expect(createCorrection).toHaveBeenCalledWith({
      analysis_id: 'analysis-1',
      file: 'index.html',
      language: 'html',
      source_code: SOURCE,
      mode: 'full',
      issues: [
        {
          message: ISSUE_A.message,
          severity: 'medium',
          line: 5,
          code: 'missing_alt',
          cause: 'missing_alt',
        },
        {
          message: ISSUE_B.message,
          severity: 'medium',
          line: 6,
          code: 'missing_alt',
          cause: 'missing_alt',
        },
      ],
    });
    expect(buttons(element, 'Corrigir todos com IA')).toHaveLength(1);
    expect(element.querySelectorAll('.issue-list__full-panel')).toHaveLength(1);
  });

  it('keeps the per-issue single correction flow intact', async () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir com IA')[0]?.click();
    fixture.detectChanges();
    const singlePanel = element.querySelector('.issue__panel') as HTMLElement;
    expect(singlePanel).not.toBeNull();

    const request = Array.from(singlePanel.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Corrigir com IA'),
    );
    request?.click();
    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledTimes(1);
    const payload = createCorrection.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload['issue']).toBeDefined();
    expect(payload['mode']).toBeUndefined();
    expect(payload['issues']).toBeUndefined();
  });

  it.each([
    [413, 'O código enviado é grande demais para correção.'],
    [502, 'A IA retornou uma correção inválida.'],
    [503, 'A correção de IA não está configurada no servidor.'],
    [504, 'A IA demorou para responder. Tente novamente ou use um arquivo menor.'],
  ])('shows a PT-BR message for HTTP %s', async (status, expected) => {
    createCorrection.mockRejectedValue(
      new ApiError(status >= 500 ? 'server' : 'validation', 'provider failure', { status }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    await settle(fixture);

    expect(element.textContent).toContain(expected);
    expect(buttons(element, 'Corrigir todos com IA (2)')[0]?.disabled).toBe(false);
  });

  it('resets the full request token when the issue list identity changes', async () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    await settle(fixture);
    expect(createCorrection).toHaveBeenCalledTimes(1);

    // The list empties (the full panel is destroyed) and comes back later: the
    // stale token must not make the new panel request automatically.
    fixture.componentRef.setInput('issues', []);
    fixture.detectChanges();
    await settle(fixture);

    fixture.componentRef.setInput('issues', [ISSUE_A, ISSUE_B]);
    fixture.detectChanges();
    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledTimes(1);
    expect(buttons(element, 'Corrigir todos com IA (2)')).toHaveLength(1);
  });

  it('explains the full-mode issue limit (HTTP 422) in PT-BR', async () => {
    createCorrection.mockRejectedValue(
      new ApiError(
        'validation',
        'Too many issues for a full correction (11); the limit is 10.',
        { status: 422 },
      ),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'Há problemas demais para corrigir de uma vez. Reduza a quantidade e tente novamente.',
    );
    expect(element.textContent).not.toContain('the limit is 10');
  });

  it('explains a safety rejection (HTTP 422) in PT-BR', async () => {
    createCorrection.mockRejectedValue(
      new ApiError(
        'validation',
        'Dados inválidos: The proposed correction was rejected by safety checks.',
        { status: 422 },
      ),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttons(element, 'Corrigir todos com IA (2)')[0]?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'A correção proposta foi rejeitada pelas verificações de segurança.',
    );
  });
});
