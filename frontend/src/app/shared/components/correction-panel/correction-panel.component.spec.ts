import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { ApiError } from '../../../core/api/api-error.mapper';
import { Correction } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { CorrectionPanelComponent } from './correction-panel.component';

const ISSUE = {
  message: 'Bloco sem fechamento',
  severity: 'high',
  line: 2,
  column: 3,
  cause: 'unclosed_block',
  code: 'unclosed_block',
  language: 'advpl',
  origin: 'validator',
  analysis_kind: 'heuristic_validation',
  file: 'src/app.prg',
} as const;

const CORRECTION: Correction = {
  id: 'c1',
  analysis_id: 'analysis-1',
  language: 'advpl',
  file: 'src/app.prg',
  issue_ref: 'Bloco sem fechamento',
  original_code: 'User Function X()\nReturn\n',
  corrected_code: 'User Function X()\nReturn\n// ajuste\n',
  diff: [
    '--- a/src/app.prg',
    '+++ b/src/app.prg',
    '@@ -1,2 +1,3 @@',
    ' User Function X()',
    ' Return',
    '+// ajuste',
    '',
  ].join('\n'),
  explanation: 'Ajuste do bloco.',
  origin: 'ai',
  post_validation: {
    status: 'passed',
    target_resolved: true,
    issues: [],
    summary: 'Problema original resolvido.',
  },
  status: 'pending',
  model: 'fake',
  protheus_version: '12.1.2410',
  created_at: '2026-10-28T12:00:00Z',
  decided_at: null,
};

describe('CorrectionPanelComponent', () => {
  const createCorrection = vi.fn();
  const decideCorrection = vi.fn();
  let authConfigured = true;

  beforeEach(async () => {
    authConfigured = true;
    createCorrection.mockReset();
    decideCorrection.mockReset();
    createCorrection.mockResolvedValue(CORRECTION);

    await TestBed.configureTestingModule({
      imports: [CorrectionPanelComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: { createCorrection, decideCorrection },
        },
        {
          provide: AuthService,
          useValue: {
            get configured() {
              return authConfigured;
            },
            get isAuthConfigured() {
              return authConfigured;
            },
          },
        },
      ],
    }).compileComponents();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function settle(fixture: ComponentFixture<CorrectionPanelComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function create(authenticated = false): ComponentFixture<CorrectionPanelComponent> {
    const fixture = TestBed.createComponent(CorrectionPanelComponent);
    fixture.componentRef.setInput('issue', ISSUE);
    fixture.componentRef.setInput('source', CORRECTION.original_code);
    fixture.componentRef.setInput('language', 'advpl');
    fixture.componentRef.setInput('file', 'src/app.prg');
    fixture.componentRef.setInput('analysisId', 'analysis-1');
    fixture.componentRef.setInput('protheusVersion', '12.1.2410');
    fixture.componentRef.setInput('authenticated', authenticated);
    fixture.detectChanges();
    return fixture;
  }

  function buttonByText(element: HTMLElement, text: string): HTMLButtonElement | undefined {
    return Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes(text),
    );
  }

  it('shows the AI warning and the correction action before a request', () => {
    const element = create().nativeElement as HTMLElement;

    expect(element.textContent).toContain('Sugestão gerada por IA — revisar antes de aplicar.');
    expect(element.textContent).toContain('Análise estática — não valida compilação.');
    expect(buttonByText(element, 'Corrigir com IA')).toBeDefined();
    expect(element.textContent).not.toContain('Código original');
  });

  it('requests a correction, prevents button spam and renders code, diff and validation', async () => {
    createCorrection.mockResolvedValue({
      ...CORRECTION,
      corrected_code: 'User Function X()\nReturn\n// <script>alert(1)</script>\n',
      diff: '--- a/src/app.prg\n+++ b/src/app.prg\n@@ -1,2 +1,3 @@\n User Function X()\n- Return\n+// <script>alert(1)</script>\n',
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    fixture.detectChanges();
    expect(buttonByText(element, 'Corrigir com IA')?.disabled).toBe(true);

    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledWith({
      analysis_id: 'analysis-1',
      file: 'src/app.prg',
      language: 'advpl',
      source_code: CORRECTION.original_code,
      issue: {
        message: 'Bloco sem fechamento',
        severity: 'high',
        line: 2,
        column: 3,
        code: 'unclosed_block',
        cause: 'unclosed_block',
      },
      protheus_version: '12.1.2410',
    });

    expect(element.textContent).toContain('Código original');
    expect(element.textContent).toContain('Código corrigido');
    expect(element.textContent).toContain('Diferenças');
    expect(element.textContent).toContain('Ajuste do bloco.');
    expect(element.textContent).toContain('Validação local (heurística)');
    expect(element.textContent).toContain('Passou');
    expect(element.textContent).toContain(
      'Validação local (heurística) aprovada: o problema alvo foi resolvido e nenhum erro novo foi detectado.',
    );
    expect(element.textContent).toContain('não é compilação oficial');

    expect(element.querySelector('.diff__line--add')).not.toBeNull();
    expect(element.querySelector('.diff__line--remove')).not.toBeNull();
    expect(element.querySelector('.diff__line--hunk')).not.toBeNull();

    // The diff and the corrected code are rendered as text, never as HTML.
    expect(element.querySelector('script')).toBeNull();
    expect(element.textContent).toContain('<script>alert(1)</script>');
  });

  it('clears a generated correction when the issue identity changes', async () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    expect(element.textContent).toContain('Código corrigido');

    fixture.componentRef.setInput('issue', {
      ...ISSUE,
      message: 'Outro problema',
      line: 9,
    });
    fixture.detectChanges();
    await settle(fixture);

    expect(element.textContent).not.toContain('Código corrigido');
    expect(element.textContent).not.toContain('Ajuste do bloco.');
    expect(buttonByText(element, 'Corrigir com IA')).toBeDefined();
  });

  it('drops a late correction response for the previous issue', async () => {
    let resolveCorrection: (value: Correction) => void = () => undefined;
    createCorrection.mockReturnValue(
      new Promise<Correction>((resolve) => {
        resolveCorrection = resolve;
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    fixture.detectChanges();

    fixture.componentRef.setInput('issue', { ...ISSUE, message: 'Outro problema', line: 9 });
    fixture.detectChanges();

    resolveCorrection(CORRECTION);
    await settle(fixture);

    expect(element.textContent).not.toContain('Código corrigido');
    expect(element.textContent).toContain('Corrigir com IA');
  });

  it('does not claim the target was resolved when local validation failed', async () => {
    createCorrection.mockResolvedValue({
      ...CORRECTION,
      post_validation: {
        status: 'failed',
        target_resolved: true,
        issues: [],
        summary:
          'Correction failed local validation: the corrected code is identical to the original file.',
      },
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Falhou');
    expect(element.textContent).toContain('o código corrigido é idêntico ao arquivo original');
    expect(element.textContent).not.toContain('O alvo original foi resolvido.');
    expect(element.textContent).not.toContain('Correction failed local validation');
  });

  it('copies the corrected code and exposes accessible feedback', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Copiar')?.click();
    await settle(fixture);

    expect(writeText).toHaveBeenCalledWith(CORRECTION.corrected_code);
    expect(buttonByText(element, 'Copiado')).toBeDefined();
    expect(element.textContent).toContain('Código corrigido copiado.');
    expect(element.querySelector('[aria-live]')).not.toBeNull();
  });

  it('exports the corrected code and the diff as text files', async () => {
    const blobs: Blob[] = [];
    const downloads: string[] = [];
    const createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return `blob:${blobs.length}`;
    });
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: revokeObjectURL,
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });

    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;
    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    buttonByText(element, 'Exportar código')?.click();
    buttonByText(element, 'Exportar diferenças')?.click();
    fixture.detectChanges();

    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(blobs[0]?.size).toBeGreaterThan(0);
    expect(blobs[0]?.type).toContain('text/plain');
    expect(blobs[1]?.type).toContain('text/x-diff');
    expect(downloads).toEqual(['app.corrected.prg', 'app.diff.txt']);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
    expect(element.textContent).toContain('Download das diferenças iniciado.');
  });

  it('approves a pending correction and reflects the new status', async () => {
    decideCorrection.mockResolvedValue({
      ...CORRECTION,
      status: 'approved',
      decided_at: '2026-10-28T13:00:00Z',
    });
    const fixture = create(true);
    const element = fixture.nativeElement as HTMLElement;
    const decided = vi.fn();
    fixture.componentInstance.decided.subscribe(decided);

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Aprovar')?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledWith('c1', { status: 'approved' });
    expect(decided).toHaveBeenCalledTimes(1);
    expect(element.textContent).toContain('Correção aprovada.');
    expect(element.textContent).toContain('Aprovada');
    expect(buttonByText(element, 'Rejeitar')).toBeUndefined();
  });

  it('rejects a pending correction', async () => {
    decideCorrection.mockResolvedValue({
      ...CORRECTION,
      status: 'rejected',
      decided_at: '2026-10-28T13:00:00Z',
    });
    const fixture = create(true);
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Rejeitar')?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledWith('c1', { status: 'rejected' });
    expect(element.textContent).toContain('Correção rejeitada.');
    expect(element.textContent).toContain('Rejeitada');
  });

  it('keeps anonymous users informed and asks for login instead of deciding', async () => {
    const fixture = create(false);
    const element = fixture.nativeElement as HTMLElement;
    const loginRequested = vi.fn();
    fixture.componentInstance.loginRequested.subscribe(loginRequested);

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(buttonByText(element, 'Aprovar')).toBeUndefined();
    expect(element.textContent).toContain('Entre na sua conta para aprovar ou rejeitar');
    buttonByText(element, 'Entrar')?.click();

    expect(loginRequested).toHaveBeenCalledTimes(1);
    expect(decideCorrection).not.toHaveBeenCalled();
  });

  it('asks for a real login without opening an unavailable Firebase flow', async () => {
    authConfigured = false;
    const fixture = create(false);
    const element = fixture.nativeElement as HTMLElement;
    const loginRequested = vi.fn();
    fixture.componentInstance.loginRequested.subscribe(loginRequested);

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Entrar')?.click();
    fixture.detectChanges();

    expect(loginRequested).not.toHaveBeenCalled();
    expect(element.textContent).toContain('Login não disponível');
    expect(decideCorrection).not.toHaveBeenCalled();
  });

  it('explains a 409 conflict when the correction was already decided', async () => {
    decideCorrection.mockRejectedValue(
      new ApiError('unknown', 'The correction has already been decided.', { status: 409 }),
    );
    const fixture = create(true);
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Aprovar')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Esta correção já foi decidida.');
  });

  it.each([
    [503, 'A correção de IA não está configurada no servidor.'],
    [504, 'A IA demorou para responder. Tente novamente ou use um arquivo menor.'],
    [502, 'A IA retornou uma correção inválida.'],
    [429, 'Muitas solicitações de correção.'],
  ])('shows a clear PT-BR message for HTTP %s', async (status, expected) => {
    createCorrection.mockRejectedValue(
      new ApiError(status >= 500 ? 'server' : 'rate-limited', 'provider failure', {
        status,
        retryAfterSeconds: status === 429 ? 12 : null,
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain(expected);
    expect(buttonByText(element, 'Corrigir com IA')?.disabled).toBe(false);
  });

  it('shows the retry delay for HTTP 429', async () => {
    createCorrection.mockRejectedValue(
      new ApiError('rate-limited', 'provider failure', {
        status: 429,
        retryAfterSeconds: 12,
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'Muitas solicitações de correção. Aguarde 12 s e tente novamente.',
    );
    expect(buttonByText(element, 'Corrigir com IA')?.disabled).toBe(false);
  });

  it('explains a 422 without targets in PT-BR', async () => {
    createCorrection.mockRejectedValue(
      new ApiError('validation', 'No issues to correct in the submitted source.', {
        status: 422,
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'Nenhum problema foi encontrado para corrigir neste arquivo.',
    );
    expect(element.textContent).not.toContain('No issues to correct');
  });

  it('explains a safety rejection (HTTP 422) instead of a generic validation error', async () => {
    createCorrection.mockRejectedValue(
      new ApiError('validation', 'Dados inválidos: The proposed correction was rejected by safety checks.', {
        status: 422,
      }),
    );
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain(
      'A correção proposta foi rejeitada pelas verificações de segurança.',
    );
    expect(buttonByText(element, 'Corrigir com IA')?.disabled).toBe(false);
  });

  it('shows the resolved count when the whole file passes validation', async () => {
    createCorrection.mockResolvedValue({
      ...CORRECTION,
      post_validation: {
        status: 'passed',
        target_resolved: true,
        issues: [],
        summary:
          'Local structural validation resolved 1 of 1 original finding(s) and found no relevant new finding. This is a deterministic local check, not an official Protheus validation.',
        issues_resolved: [
          {
            message: 'Image is missing an alt attribute.',
            severity: 'medium',
            cause: 'missing_alt',
            line: 8,
          },
        ],
        issues_remaining: [],
        issues_new: [],
        issues_warnings: [],
      },
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Passou');
    expect(element.textContent).toContain('1 de 1 resolvidos');
    expect(element.textContent).toContain('O alvo original foi resolvido.');
    expect(element.textContent).not.toContain('Problemas originais que permanecem');
  });

  it('lists remaining original findings instead of claiming the file is corrected', async () => {
    createCorrection.mockResolvedValue({
      ...CORRECTION,
      post_validation: {
        status: 'failed',
        target_resolved: true,
        issues: [],
        summary:
          'Correction failed local validation: target resolved but 1 original issue(s) remain. This is a deterministic local check, not an official Protheus validation.',
        issues_resolved: [
          {
            message: 'Image is missing an alt attribute.',
            severity: 'medium',
            cause: 'missing_alt',
            line: 5,
          },
        ],
        issues_remaining: [
          {
            message: "Tag '<div>' is not closed.",
            severity: 'high',
            cause: 'unclosed_tag',
            line: 2,
          },
        ],
        issues_new: [],
        issues_warnings: [],
      },
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Falhou');
    expect(element.textContent).toContain('1 de 2 resolvidos');
    expect(element.textContent).toContain('Problemas originais que permanecem');
    expect(element.textContent).toContain('Tag sem fechamento');
    expect(element.textContent).toContain(
      'o problema alvo foi resolvido, mas 1 problema(s) original(is) permanecem',
    );
    expect(element.textContent).not.toContain('O alvo original foi resolvido.');
    expect(element.textContent).not.toContain('arquivo corrigido');
  });

  it('lists new medium findings and low-severity warnings separately', async () => {
    createCorrection.mockResolvedValue({
      ...CORRECTION,
      post_validation: {
        status: 'failed',
        target_resolved: true,
        issues: [],
        summary:
          'Correction failed local validation: 1 new medium-severity finding(s) were introduced. This is a deterministic local check, not an official Protheus validation.',
        issues_resolved: [],
        issues_remaining: [],
        issues_new: [
          {
            message: 'Image is missing an alt attribute.',
            severity: 'medium',
            cause: 'missing_alt',
            line: 9,
          },
        ],
        issues_warnings: [
          {
            message: 'Document has no viewport meta tag.',
            severity: 'low',
            cause: 'missing_viewport',
            line: 1,
          },
        ],
      },
    });
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Novos problemas introduzidos');
    expect(element.textContent).toContain('Imagem sem texto alternativo');
    expect(element.textContent).toContain(
      '1 novo(s) achado(s) de severidade média foram introduzidos',
    );
    expect(element.textContent).toContain('Avisos de baixa severidade');
    expect(element.textContent).toContain('Meta viewport ausente');
    expect(element.textContent).toContain('src/app.prg:1');
  });

  it('keeps the user approval separate from a failed local validation', async () => {
    const failed: Correction = {
      ...CORRECTION,
      post_validation: {
        status: 'failed',
        target_resolved: true,
        issues: [],
        summary:
          'Correction failed local validation: target resolved but 1 original issue(s) remain. This is a deterministic local check, not an official Protheus validation.',
        issues_resolved: [],
        issues_remaining: [
          {
            message: 'Image is missing an alt attribute.',
            severity: 'medium',
            cause: 'missing_alt',
            line: 9,
          },
        ],
        issues_new: [],
        issues_warnings: [],
      },
    };
    createCorrection.mockResolvedValue(failed);
    decideCorrection.mockResolvedValue({
      ...failed,
      status: 'approved',
      decided_at: '2026-10-28T13:00:00Z',
    });
    const fixture = create(true);
    const element = fixture.nativeElement as HTMLElement;

    buttonByText(element, 'Corrigir com IA')?.click();
    await settle(fixture);
    buttonByText(element, 'Aprovar')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Falhou');
    expect(element.textContent).toContain('Aprovada');
    expect(element.textContent).toContain(
      'O status da decisão é separado da validação local acima',
    );
  });
});

// ---------------------------------------------------- Fase D: modo full (D1)
const SECOND_ISSUE = {
  message: 'Bloco interno sem fechamento',
  severity: 'medium',
  line: 9,
  cause: 'unclosed_block',
} as const;

const FULL_CORRECTION: Correction = {
  ...CORRECTION,
  issue_ref: 'full:2',
  corrected_code: 'User Function X()\nReturn\n// ajuste 1\n// ajuste 2\n',
  diff: [
    '--- a/src/app.prg',
    '+++ b/src/app.prg',
    '@@ -1,2 +1,4 @@',
    ' User Function X()',
    ' Return',
    '+// ajuste 1',
    '+// ajuste 2',
    '',
  ].join('\n'),
  explanation: 'Ajustes consolidados para os dois problemas.',
  post_validation: {
    status: 'passed',
    target_resolved: true,
    issues: [],
    summary:
      'Local structural validation resolved 2 of 2 target issue(s) and found no relevant new finding. This is a deterministic local check, not an official Protheus validation.',
    issues_resolved: [
      { message: 'Bloco sem fechamento', severity: 'high', cause: 'unclosed_block', line: 2 },
      { message: 'Bloco interno sem fechamento', severity: 'medium', cause: 'unclosed_block', line: 9 },
    ],
    issues_remaining: [],
    issues_new: [],
    issues_warnings: [],
  },
};

describe('CorrectionPanelComponent (full mode)', () => {
  const createCorrection = vi.fn();
  const decideCorrection = vi.fn();

  beforeEach(async () => {
    createCorrection.mockReset();
    decideCorrection.mockReset();
    createCorrection.mockResolvedValue(FULL_CORRECTION);

    await TestBed.configureTestingModule({
      imports: [CorrectionPanelComponent],
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

  async function settle(fixture: ComponentFixture<CorrectionPanelComponent>): Promise<void> {
    for (let index = 0; index < 10; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      fixture.detectChanges();
    }
  }

  function createFull(
    requestToken = 1,
    authenticated = false,
  ): ComponentFixture<CorrectionPanelComponent> {
    const fixture = TestBed.createComponent(CorrectionPanelComponent);
    fixture.componentRef.setInput('mode', 'full');
    fixture.componentRef.setInput('issues', [ISSUE, SECOND_ISSUE]);
    fixture.componentRef.setInput('source', CORRECTION.original_code);
    fixture.componentRef.setInput('language', 'advpl');
    fixture.componentRef.setInput('file', 'src/app.prg');
    fixture.componentRef.setInput('analysisId', 'analysis-1');
    fixture.componentRef.setInput('protheusVersion', '12.1.2410');
    fixture.componentRef.setInput('authenticated', authenticated);
    fixture.componentRef.setInput('requestToken', requestToken);
    fixture.detectChanges();
    return fixture;
  }

  it('requests one correction for every listed issue and shows the count', async () => {
    const fixture = createFull();
    const element = fixture.nativeElement as HTMLElement;

    await settle(fixture);

    expect(createCorrection).toHaveBeenCalledTimes(1);
    expect(createCorrection).toHaveBeenCalledWith({
      analysis_id: 'analysis-1',
      file: 'src/app.prg',
      language: 'advpl',
      source_code: CORRECTION.original_code,
      mode: 'full',
      issues: [
        {
          message: 'Bloco sem fechamento',
          severity: 'high',
          line: 2,
          column: 3,
          code: 'unclosed_block',
          cause: 'unclosed_block',
        },
        {
          message: 'Bloco interno sem fechamento',
          severity: 'medium',
          line: 9,
          cause: 'unclosed_block',
        },
      ],
      protheus_version: '12.1.2410',
    });
    expect(element.textContent).toContain('Correção de 2 problemas com IA');
    expect(element.textContent).toContain('2 problemas incluídos');
    expect(element.textContent).toContain('Código corrigido');
    expect(element.textContent).toContain('Diferenças');
    expect(element.textContent).toContain('Ajustes consolidados para os dois problemas.');
    expect(element.textContent).toContain('2 de 2 resolvidos');
    expect(element.textContent).toContain('Todos os problemas incluídos foram resolvidos.');
  });

  it('does not request before the parent increments the request token', async () => {
    const fixture = createFull(0);
    const element = fixture.nativeElement as HTMLElement;

    await settle(fixture);

    expect(createCorrection).not.toHaveBeenCalled();
    expect(element.textContent).toContain('Correção de 2 problemas com IA');
  });

  it('signals the busy state while the full request is in flight', async () => {
    let resolveCorrection: (value: Correction) => void = () => undefined;
    createCorrection.mockReturnValue(
      new Promise<Correction>((resolve) => {
        resolveCorrection = resolve;
      }),
    );
    const fixture = createFull(0);
    const busy: boolean[] = [];
    fixture.componentInstance.busyChange.subscribe((value) => busy.push(value));

    fixture.componentRef.setInput('requestToken', 1);
    fixture.detectChanges();

    expect(busy).toContain(true);

    resolveCorrection(FULL_CORRECTION);
    await settle(fixture);

    expect(busy[busy.length - 1]).toBe(false);
  });

  it('approves a full correction and keeps the decision separate', async () => {
    decideCorrection.mockResolvedValue({
      ...FULL_CORRECTION,
      status: 'approved',
      decided_at: '2026-10-28T13:00:00Z',
    });
    const fixture = createFull(1, true);
    const element = fixture.nativeElement as HTMLElement;
    await settle(fixture);

    buttonByText(element, 'Aprovar')?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledWith('c1', { status: 'approved' });
    expect(element.textContent).toContain('Correção aprovada.');
    expect(element.textContent).toContain('Aprovada');
  });

  it('rejects a full correction', async () => {
    decideCorrection.mockResolvedValue({
      ...FULL_CORRECTION,
      status: 'rejected',
      decided_at: '2026-10-28T13:00:00Z',
    });
    const fixture = createFull(1, true);
    const element = fixture.nativeElement as HTMLElement;
    await settle(fixture);

    buttonByText(element, 'Rejeitar')?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledWith('c1', { status: 'rejected' });
    expect(element.textContent).toContain('Rejeitada');
  });

  it('does not clear the busy state when a superseded request finishes', async () => {
    let resolveFirst: (value: Correction) => void = () => undefined;
    let resolveSecond: (value: Correction) => void = () => undefined;
    createCorrection
      .mockReturnValueOnce(
        new Promise<Correction>((resolve) => {
          resolveFirst = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise<Correction>((resolve) => {
          resolveSecond = resolve;
        }),
      );
    const fixture = createFull(0);
    const busy: boolean[] = [];
    fixture.componentInstance.busyChange.subscribe((value) => busy.push(value));

    fixture.componentRef.setInput('requestToken', 1);
    fixture.detectChanges();
    expect(createCorrection).toHaveBeenCalledTimes(1);

    // A new identity supersedes the first request, then a second request is
    // started while the first one is still in flight.
    fixture.componentRef.setInput('issues', [ISSUE]);
    fixture.detectChanges();
    fixture.componentRef.setInput('requestToken', 2);
    fixture.detectChanges();
    expect(createCorrection).toHaveBeenCalledTimes(2);
    expect(busy[busy.length - 1]).toBe(true);

    resolveFirst(FULL_CORRECTION);
    await settle(fixture);

    // The old request must not report "not busy" for the current one.
    expect(busy[busy.length - 1]).toBe(true);

    resolveSecond(FULL_CORRECTION);
    await settle(fixture);

    expect(busy[busy.length - 1]).toBe(false);
  });

  it('shows a PT-BR message when the full request fails', async () => {
    createCorrection.mockRejectedValue(
      new ApiError('server', 'provider failure', { status: 504 }),
    );
    const fixture = createFull();
    const element = fixture.nativeElement as HTMLElement;

    await settle(fixture);

    expect(element.textContent).toContain(
      'A IA demorou para responder. Tente novamente ou use um arquivo menor.',
    );
  });
});

function buttonByText(element: HTMLElement, text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find((button) =>
    (button.textContent ?? '').includes(text),
  );
}
