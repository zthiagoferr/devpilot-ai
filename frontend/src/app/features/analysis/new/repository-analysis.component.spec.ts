import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { ApiError } from '../../../core/api/api-error.mapper';
import {
  CorrectionBatchResponse,
  Correction,
  Relations,
  RepositoryLoad,
} from '../../../core/api/api.types';
import { RepositoryAnalysisComponent } from './repository-analysis.component';

const RELATIONS: Relations = {
  version: 1,
  generated_by: 'deterministic',
  truncated: false,
  tree_complete: true,
  summary: { resolved: 3, missing: 1, external: 0, unknown: 2 },
  edges: [],
  nodes: [],
  protheus: {
    apps_json: { path: 'apps.json', present: true, parsed: true, applications: 1, keys: ['app'] },
  },
};

const PAYLOAD: RepositoryLoad = {
  files: [
    {
      path: 'src/sample.py',
      size: 20,
      source_code: 'print("sample")',
      language: 'python',
      language_source: 'extension',
      confidence: 0.95,
    },
    {
      path: 'tests/test_sample.py',
      size: 10,
      source_code: 'assert True',
      language: 'python',
      language_source: 'extension',
      confidence: 0.95,
    },
    {
      path: 'src/financeiro.prg',
      size: 30,
      source_code: 'User Function Teste()\nReturn\n',
      language: 'advpl',
      language_source: 'extension',
      confidence: 0.9,
    },
  ],
  truncated: false,
  paths: ['src/sample.py', 'tests/test_sample.py', 'src/financeiro.prg', 'apps.json'],
  tree_complete: true,
  relations: RELATIONS,
  protheus: RELATIONS.protheus?.apps_json,
};

const ANALYSIS = {
  id: 'abc',
  task: 'code',
  project_name: 'Sample',
  source_code: 'print("sample")',
  repository_url: 'pypa/sampleproject',
  result: { score: 88, issues: [], summary: 'ok' },
  status: 'completed',
  created_at: '2026-04-01T12:00:00Z',
};

function correction(id: string, file: string): Correction {
  return {
    id,
    analysis_id: 'abc',
    language: 'python',
    file,
    issue_ref: 'print',
    original_code: 'print ("x")\n',
    corrected_code: 'print("x")\n',
    diff: `--- a/${file}\n+++ b/${file}\n@@ -1 +1 @@\n-print ("x")\n+print("x")\n`,
    explanation: `Ajuste em ${file}.`,
    origin: 'ai',
    post_validation: {
      status: 'passed',
      target_resolved: true,
      issues: [],
      summary: 'ok',
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
  };
}

const BATCH: CorrectionBatchResponse = {
  results: [
    {
      path: 'src/sample.py',
      status: 'completed',
      correction: correction('c1', 'src/sample.py'),
      issues_targeted: 1,
    },
    {
      path: 'tests/test_sample.py',
      status: 'completed',
      correction: correction('c2', 'tests/test_sample.py'),
      issues_targeted: 1,
    },
    {
      path: 'src/financeiro.prg',
      status: 'failed',
      issues_targeted: 0,
      reason: 'provider_error',
      error_code: 'provider_error',
      error_status: 502,
      error_detail: 'The AI provider could not complete this file.',
    },
  ],
  files_total: 3,
  files_completed: 2,
  files_failed: 1,
  files_skipped: 0,
  issues_resolved_total: 2,
  issues_remaining_total: 0,
  issues_new_total: 0,
  partial: true,
  budget_exceeded: false,
};

describe('RepositoryAnalysisComponent', () => {
  const loadRepository = vi.fn();
  const createAnalysis = vi.fn();
  const createCorrectionBatch = vi.fn();
  const decideCorrection = vi.fn();
  const createCorrection = vi.fn();

  beforeEach(async () => {
    loadRepository.mockReset();
    createAnalysis.mockReset();
    createCorrectionBatch.mockReset();
    decideCorrection.mockReset();
    createCorrection.mockReset();
    loadRepository.mockResolvedValue(PAYLOAD);
    createAnalysis.mockResolvedValue(ANALYSIS);

    await TestBed.configureTestingModule({
      imports: [RepositoryAnalysisComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: {
            loadRepository,
            createAnalysis,
            createCorrectionBatch,
            decideCorrection,
            createCorrection,
          },
        },
      ],
    }).compileComponents();
  });

  async function settle(fixture: ComponentFixture<RepositoryAnalysisComponent>): Promise<void> {
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

  function selectById(element: HTMLElement, id: string): HTMLSelectElement | null {
    return element.querySelector<HTMLSelectElement>(`#${id}`);
  }

  function clickLoad(element: HTMLElement): void {
    const loadButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Carregar arquivos'),
    );
    loadButton?.click();
  }

  it('loads files, then submits the selected path, repository origin and context', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const project = inputByLabel(element, 'Nome do projeto');
    const repository = inputByLabel(element, 'Repositório GitHub');
    const branch = inputByLabel(element, 'Branch');
    for (const [input, value] of [
      [project, 'Sample'],
      [repository, 'pypa/sampleproject'],
      [branch, 'main'],
    ] as const) {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    clickLoad(element);
    await settle(fixture);

    expect(loadRepository).toHaveBeenCalledWith(
      'pypa/sampleproject',
      'main',
      expect.any(AbortSignal),
      'auto',
    );

    const fileSelect = selectById(element, 'repository-file');
    expect(fileSelect?.disabled).toBe(false);
    expect(fileSelect?.options.length).toBe(4);
    expect(element.textContent).toContain('apps.json detectado');
    expect(element.textContent).toContain('Referências:');

    if (fileSelect !== null) {
      fileSelect.value = 'src/sample.py';
      fileSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    const submit = element.querySelector<HTMLButtonElement>('button[type="submit"]');
    expect(submit?.disabled).toBe(false);
    submit?.click();
    await settle(fixture);

    expect(createAnalysis).toHaveBeenCalledWith({
      task: 'code',
      project_name: 'Sample',
      source_code: 'print("sample")',
      repository_url: 'pypa/sampleproject',
      file_path: 'src/sample.py',
      language: 'auto',
      branch: 'main',
      repository_context: {
        files: [
          {
            path: 'src/sample.py',
            source_code: 'print("sample")',
            language: 'python',
          },
          {
            path: 'tests/test_sample.py',
            source_code: 'assert True',
            language: 'python',
          },
          {
            path: 'src/financeiro.prg',
            source_code: 'User Function Teste()\nReturn\n',
            language: 'advpl',
          },
        ],
        paths: ['src/sample.py', 'tests/test_sample.py', 'src/financeiro.prg', 'apps.json'],
        tree_complete: true,
        truncated: false,
      },
    });
  });

  it('filters the loaded files by language and selects one', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'owner/mixed';
    repository.dispatchEvent(new Event('input', { bubbles: true }));
    clickLoad(element);
    await settle(fixture);

    const filter = selectById(element, 'repository-language-filter');
    expect(filter?.options.length).toBe(3);
    if (filter !== null) {
      filter.value = 'advpl';
      filter.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    const fileSelect = selectById(element, 'repository-file');
    expect(fileSelect?.options.length).toBe(2);
    expect(fileSelect?.textContent).toContain('src/financeiro.prg');
    expect(fileSelect?.textContent).not.toContain('src/sample.py');

    const fileRow = Array.from(element.querySelectorAll<HTMLButtonElement>('.file-row')).find(
      (button) => (button.textContent ?? '').includes('src/financeiro.prg'),
    );
    fileRow?.click();
    fixture.detectChanges();

    expect(fixture.componentInstance['store'].selectedPath()).toBe('src/financeiro.prg');
  });

  it('sends the ADVPL Protheus version and detected context', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const project = inputByLabel(element, 'Nome do projeto');
    project.value = 'Financeiro';
    project.dispatchEvent(new Event('input', { bubbles: true }));

    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'owner/advpl';
    repository.dispatchEvent(new Event('input', { bubbles: true }));

    const languageSelect = selectById(element, 'repository-language-filter');
    // The language selector lives before the filter; use the first select.
    const selects = element.querySelectorAll<HTMLSelectElement>('select');
    const language = selects[0];
    expect(languageSelect).toBeNull();
    if (language !== null) {
      language.value = 'advpl';
      language.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    const version = inputByLabel(element, 'Versão Protheus');
    version.value = '12.1.2410';
    version.dispatchEvent(new Event('input', { bubbles: true }));

    clickLoad(element);
    await settle(fixture);

    expect(element.textContent).toContain('não exige Protheus instalado');

    const fileSelect = selectById(element, 'repository-file');
    if (fileSelect !== null) {
      fileSelect.value = 'src/financeiro.prg';
      fileSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    element.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    await settle(fixture);

    expect(createAnalysis).toHaveBeenCalledWith(
      expect.objectContaining({
        source_code: 'User Function Teste()\nReturn\n',
        file_path: 'src/financeiro.prg',
        language: 'advpl',
        protheus_version: '12.1.2410',
      }),
    );
  });

  it('keeps the placeholder selected until the user picks a file', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'pypa/sampleproject';
    repository.dispatchEvent(new Event('input', { bubbles: true }));

    clickLoad(element);
    await settle(fixture);

    const fileSelect = selectById(element, 'repository-file');
    expect(fileSelect?.value).toBe('');

    const submit = element.querySelector<HTMLButtonElement>('button[type="submit"]');
    submit?.click();
    await settle(fixture);

    expect(createAnalysis).not.toHaveBeenCalled();
    expect(element.textContent).toContain('Selecione um arquivo do repositório.');
  });

  it('shows the empty-repository message and keeps the select disabled', async () => {
    loadRepository.mockResolvedValue({
      files: [],
      truncated: false,
      message: 'No eligible Python, ADVPL, HTML5, CSS3, or JavaScript files were found.',
    });

    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'owner/docs-only';
    repository.dispatchEvent(new Event('input', { bubbles: true }));

    clickLoad(element);
    await settle(fixture);

    expect(element.textContent).toContain(
      'Nenhum arquivo Python, ADVPL, HTML5, CSS3 ou JavaScript elegível foi encontrado',
    );
    expect(element.textContent).not.toContain('No eligible Python');
    const fileSelect = selectById(element, 'repository-file');
    expect(fileSelect?.disabled).toBe(true);
    expect(element.textContent).toContain('Nenhum arquivo elegível encontrado');
  });

  function batchCheckbox(element: HTMLElement, path: string): HTMLInputElement | null {
    const label = Array.from(element.querySelectorAll<HTMLLabelElement>('.batch-option')).find(
      (item) => (item.textContent ?? '').includes(path),
    );
    return label?.querySelector<HTMLInputElement>('input[type="checkbox"]') ?? null;
  }

  function batchButton(element: HTMLElement): HTMLButtonElement | undefined {
    return Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Corrigir arquivos selecionados'),
    );
  }

  async function loadRepositoryFiles(
    fixture: ComponentFixture<RepositoryAnalysisComponent>,
    element: HTMLElement,
    payload: RepositoryLoad = PAYLOAD,
  ): Promise<void> {
    loadRepository.mockResolvedValue(payload);
    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'pypa/sampleproject';
    repository.dispatchEvent(new Event('input', { bubbles: true }));
    clickLoad(element);
    await settle(fixture);
  }

  it('lists only eligible files and enables the batch button from 1 to 3 selections', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element, {
      ...PAYLOAD,
      files: [
        ...PAYLOAD.files,
        { path: '.env', size: 20, source_code: 'TOKEN=secret', language: 'unknown' },
        { path: 'notes.txt', size: 5, source_code: 'texto', language: 'unknown' },
      ],
    });

    const checkboxes = Array.from(
      element.querySelectorAll<HTMLInputElement>('.batch-option input[type="checkbox"]'),
    );
    expect(checkboxes).toHaveLength(3);
    expect(element.textContent).toContain('2 arquivos ocultos');
    expect(batchButton(element)?.disabled).toBe(true);

    batchCheckbox(element, 'src/sample.py')?.click();
    fixture.detectChanges();
    expect(batchButton(element)?.disabled).toBe(false);
    expect(batchButton(element)?.textContent).toContain('(1)');

    batchCheckbox(element, 'tests/test_sample.py')?.click();
    batchCheckbox(element, 'src/financeiro.prg')?.click();
    fixture.detectChanges();

    expect(batchButton(element)?.textContent).toContain('(3)');
    expect(element.textContent).toContain('limite de 3 arquivos atingido');
    expect(batchCheckbox(element, 'src/sample.py')?.disabled).toBe(false);

    batchCheckbox(element, 'src/sample.py')?.click();
    fixture.detectChanges();
    expect(batchButton(element)?.textContent).toContain('(2)');
    expect(
      Array.from(element.querySelectorAll('.repo-form__batch-selected-item')).map(
        (item) => item.textContent ?? '',
      ),
    ).toEqual([
      expect.stringContaining('tests/test_sample.py'),
      expect.stringContaining('src/financeiro.prg'),
    ]);
  });

  it('sends only the selected files with the repository context', async () => {
    createCorrectionBatch.mockResolvedValue(BATCH);
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);

    batchCheckbox(element, 'src/sample.py')?.click();
    batchCheckbox(element, 'src/financeiro.prg')?.click();
    fixture.detectChanges();
    batchButton(element)?.click();
    await settle(fixture);

    expect(createCorrectionBatch).toHaveBeenCalledTimes(1);
    expect(createCorrectionBatch).toHaveBeenCalledWith({
      files: [
        { path: 'src/sample.py', source_code: 'print("sample")' },
        { path: 'src/financeiro.prg', source_code: 'User Function Teste()\nReturn\n' },
      ],
      repository_context: {
        paths: PAYLOAD.paths,
        tree_complete: true,
        truncated: false,
      },
    });
  });

  it('shows the synchronous progress state and never sends the same batch twice', async () => {
    let resolveBatch: (value: CorrectionBatchResponse) => void = () => {};
    createCorrectionBatch.mockImplementation(
      () =>
        new Promise<CorrectionBatchResponse>((resolve) => {
          resolveBatch = resolve;
        }),
    );
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);
    batchCheckbox(element, 'src/sample.py')?.click();
    fixture.detectChanges();

    batchButton(element)?.click();
    fixture.detectChanges();
    batchButton(element)?.click();
    fixture.detectChanges();

    expect(createCorrectionBatch).toHaveBeenCalledTimes(1);
    expect(batchButton(element)?.disabled).toBe(true);
    expect(element.textContent).toContain('Processando 1 arquivo com IA');
    expect(element.textContent).toContain('até 90 segundos');

    resolveBatch(BATCH);
    await settle(fixture);

    expect(element.textContent).toContain('Lote concluído com falhas ou arquivos pulados.');
    expect(element.textContent).toContain('2 de 3 arquivos concluídos');
  });

  it('shows known issue counts for the analyzed file', async () => {
    createAnalysis.mockResolvedValue({
      ...ANALYSIS,
      result: {
        score: 70,
        issues: [
          { message: 'print', severity: 'low', line: 1 },
          { message: 'espaçamento', severity: 'low', line: 2 },
        ],
        summary: 'ok',
      },
    });
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);
    const project = inputByLabel(element, 'Nome do projeto');
    project.value = 'Sample';
    project.dispatchEvent(new Event('input', { bubbles: true }));
    const fileSelect = selectById(element, 'repository-file');
    if (fileSelect !== null) {
      fileSelect.value = 'src/sample.py';
      fileSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();
    element.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    await settle(fixture);

    expect(element.textContent).toContain('2 problemas conhecidos');
    expect(element.textContent).toContain('problemas não analisados');
  });

  it('links the batch to the analysis and its known issues when authenticated', async () => {
    createAnalysis.mockResolvedValue({
      ...ANALYSIS,
      result: {
        score: 70,
        issues: [
          {
            message: 'print com espaço',
            severity: 'low',
            line: 1,
            rule_id: 'spacing',
            code: 'spacing',
            cause: 'spacing',
          },
        ],
        summary: 'ok',
      },
    });
    createCorrectionBatch.mockResolvedValue(BATCH);
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.componentRef.setInput('authenticated', true);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);
    const project = inputByLabel(element, 'Nome do projeto');
    project.value = 'Sample';
    project.dispatchEvent(new Event('input', { bubbles: true }));
    const fileSelect = selectById(element, 'repository-file');
    if (fileSelect !== null) {
      fileSelect.value = 'src/sample.py';
      fileSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();
    element.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    await settle(fixture);

    batchCheckbox(element, 'src/sample.py')?.click();
    batchCheckbox(element, 'src/financeiro.prg')?.click();
    fixture.detectChanges();
    batchButton(element)?.click();
    await settle(fixture);

    expect(createCorrectionBatch).toHaveBeenCalledWith({
      analysis_id: 'abc',
      files: [
        {
          path: 'src/sample.py',
          source_code: 'print("sample")',
          issues: [
            {
              message: 'print com espaço',
              severity: 'low',
              line: 1,
              rule_id: 'spacing',
              code: 'spacing',
              cause: 'spacing',
            },
          ],
        },
        { path: 'src/financeiro.prg', source_code: 'User Function Teste()\nReturn\n' },
      ],
      repository_context: {
        paths: PAYLOAD.paths,
        tree_complete: true,
        truncated: false,
      },
    });
  });

  it('renders the batch review and keeps decisions independent per file', async () => {
    createCorrectionBatch.mockResolvedValue(BATCH);
    decideCorrection.mockResolvedValue({ ...correction('c1', 'src/sample.py'), status: 'approved' });
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.componentRef.setInput('authenticated', true);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);
    batchCheckbox(element, 'src/sample.py')?.click();
    batchCheckbox(element, 'tests/test_sample.py')?.click();
    batchCheckbox(element, 'src/financeiro.prg')?.click();
    fixture.detectChanges();
    batchButton(element)?.click();
    await settle(fixture);

    expect(element.textContent).toContain('Correção de arquivos selecionados');
    expect(element.textContent).toContain('Lote parcial');
    expect(element.textContent).toContain('falha do provedor de IA');
    expect(element.textContent).toContain('Tentar novamente');
    expect(element.querySelectorAll('.diff')).toHaveLength(2);

    const approveButtons = Array.from(element.querySelectorAll('button')).filter((button) =>
      (button.textContent ?? '').includes('Aprovar'),
    );
    expect(approveButtons).toHaveLength(2);
    approveButtons[0]?.click();
    await settle(fixture);

    expect(decideCorrection).toHaveBeenCalledTimes(1);
    const cards = element.querySelectorAll('.batch-item');
    expect(cards[0]?.textContent).toContain('Aprovada');
    expect(cards[1]?.textContent).toContain('Aguardando decisão');
  });

  it.each([
    [422, 'O lote de correção é inválido', {}],
    [503, 'A correção de IA não está configurada no servidor', {}],
    [
      429,
      'Muitas solicitações de correção. Aguarde 12 s e tente novamente.',
      { retryAfterSeconds: 12 },
    ],
    [404, 'A análise vinculada ao lote não foi encontrada', {}],
  ])('translates a global batch error %i to pt-BR', async (status, message, options) => {
    createCorrectionBatch.mockRejectedValue(
      new ApiError('validation', 'backend detail', { status, ...options }),
    );
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    await loadRepositoryFiles(fixture, element);
    batchCheckbox(element, 'src/sample.py')?.click();
    fixture.detectChanges();
    batchButton(element)?.click();
    await settle(fixture);

    expect(element.textContent).toContain(message);
    expect(element.textContent).not.toContain('backend detail');
    expect(element.textContent).not.toContain('Lote concluído');
  });

  it('emits started on submit and cleared when the form is cleared', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const started = vi.fn();
    const cleared = vi.fn();
    fixture.componentInstance.started.subscribe(started);
    fixture.componentInstance.cleared.subscribe(cleared);

    const project = inputByLabel(element, 'Nome do projeto');
    project.value = 'Sample';
    project.dispatchEvent(new Event('input', { bubbles: true }));
    const repository = inputByLabel(element, 'Repositório GitHub');
    repository.value = 'pypa/sampleproject';
    repository.dispatchEvent(new Event('input', { bubbles: true }));

    clickLoad(element);
    await settle(fixture);

    const fileSelect = selectById(element, 'repository-file');
    if (fileSelect !== null) {
      fileSelect.value = 'src/sample.py';
      fileSelect.dispatchEvent(new Event('change', { bubbles: true }));
    }
    fixture.detectChanges();

    element.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
    await settle(fixture);

    expect(started).toHaveBeenCalledTimes(1);
    expect(cleared).not.toHaveBeenCalled();

    const clearButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Limpar'),
    );
    clearButton?.click();
    fixture.detectChanges();

    expect(cleared).toHaveBeenCalledTimes(1);
    expect(started).toHaveBeenCalledTimes(1);
  });
});
