import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { Relations, RepositoryLoad } from '../../../core/api/api.types';
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

describe('RepositoryAnalysisComponent', () => {
  const loadRepository = vi.fn();
  const createAnalysis = vi.fn();

  beforeEach(async () => {
    loadRepository.mockReset();
    createAnalysis.mockReset();
    loadRepository.mockResolvedValue(PAYLOAD);
    createAnalysis.mockResolvedValue(ANALYSIS);

    await TestBed.configureTestingModule({
      imports: [RepositoryAnalysisComponent],
      providers: [
        {
          provide: ApiClient,
          useValue: { loadRepository, createAnalysis },
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
