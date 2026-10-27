import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../../core/api/api-client';
import { RepositoryLoad } from '../../../core/api/api.types';
import { RepositoryAnalysisComponent } from './repository-analysis.component';

const PAYLOAD: RepositoryLoad = {
  files: [
    { path: 'src/sample.py', size: 20, source_code: 'print("sample")' },
    { path: 'tests/test_sample.py', size: 10, source_code: 'assert True' },
  ],
  truncated: false,
};

describe('RepositoryAnalysisComponent', () => {
  const loadRepository = vi.fn();
  const createAnalysis = vi.fn();

  beforeEach(async () => {
    loadRepository.mockReset();
    createAnalysis.mockReset();
    loadRepository.mockResolvedValue(PAYLOAD);
    createAnalysis.mockResolvedValue({
      id: 'abc',
      task: 'code',
      project_name: 'Sample',
      source_code: 'print("sample")',
      repository_url: 'pypa/sampleproject',
      result: { score: 88, issues: [], summary: 'ok' },
      status: 'completed',
      created_at: '2026-04-01T12:00:00Z',
    });

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

  it('loads files, then submits the selected path and repository origin', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const inputs = element.querySelectorAll<HTMLInputElement>('input');
    const [project, repository, branch] = [inputs[0], inputs[1], inputs[2]];
    for (const [input, value] of [
      [project, 'Sample'],
      [repository, 'pypa/sampleproject'],
      [branch, 'main'],
    ] as const) {
      input!.value = value;
      input!.dispatchEvent(new Event('input', { bubbles: true }));
    }

    const loadButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Carregar arquivos'),
    );
    loadButton?.click();
    await settle(fixture);

    expect(loadRepository).toHaveBeenCalledWith(
      'pypa/sampleproject',
      'main',
      expect.any(AbortSignal),
    );

    const select = element.querySelector<HTMLSelectElement>('select');
    expect(select?.disabled).toBe(false);
    expect(select?.options.length).toBe(3);

    if (select !== null) {
      select.value = 'src/sample.py';
      select.dispatchEvent(new Event('change', { bubbles: true }));
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
      branch: 'main',
    });
  });

  it('keeps the placeholder selected until the user picks a file', async () => {
    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const repository = element.querySelectorAll<HTMLInputElement>('input')[1];
    repository!.value = 'pypa/sampleproject';
    repository!.dispatchEvent(new Event('input', { bubbles: true }));

    const loadButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Carregar arquivos'),
    );
    loadButton?.click();
    await settle(fixture);

    const select = element.querySelector<HTMLSelectElement>('select');
    expect(select?.value).toBe('');

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
      message: 'No eligible Python files were found in this repository.',
    });

    const fixture = TestBed.createComponent(RepositoryAnalysisComponent);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const repository = element.querySelectorAll<HTMLInputElement>('input')[1];
    repository!.value = 'owner/docs-only';
    repository!.dispatchEvent(new Event('input', { bubbles: true }));

    const loadButton = Array.from(element.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('Carregar arquivos'),
    );
    loadButton?.click();
    await settle(fixture);

    expect(element.textContent).toContain('No eligible Python files');
    const select = element.querySelector<HTMLSelectElement>('select');
    expect(select?.disabled).toBe(true);
  });
});
