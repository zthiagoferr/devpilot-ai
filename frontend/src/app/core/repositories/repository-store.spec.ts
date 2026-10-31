import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../api/api-client';
import { ApiError } from '../api/api-error.mapper';
import { Relations, RepositoryFile } from '../api/api.types';
import { RepositoryStore } from './repository-store';

const FILES: readonly RepositoryFile[] = [
  {
    path: 'src/sample.py',
    size: 2048,
    source_code: 'print("sample")',
    language: 'python',
    language_source: 'extension',
    confidence: 0.95,
  },
  {
    path: 'tests/test_sample.py',
    size: 512,
    source_code: 'def test_sample(): pass',
    language: 'python',
    language_source: 'extension',
    confidence: 0.95,
  },
  {
    path: 'src/financeiro.prg',
    size: 1024,
    source_code: 'User Function Teste()\nReturn\n',
    language: 'advpl',
    language_source: 'extension',
    confidence: 0.9,
  },
];

const RELATIONS: Relations = {
  version: 1,
  generated_by: 'deterministic',
  truncated: false,
  tree_complete: true,
  summary: { resolved: 2, missing: 1, external: 0, unknown: 3 },
  edges: [],
  nodes: [],
  protheus: {
    apps_json: { path: 'apps.json', present: true, parsed: true, applications: 2, keys: ['app'] },
  },
};

describe('RepositoryStore', () => {
  const loadRepository = vi.fn();
  let store: RepositoryStore;

  beforeEach(() => {
    loadRepository.mockReset();
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: { loadRepository } }],
    });
    store = TestBed.inject(RepositoryStore);
  });

  it('loads files with paths and sizes and exposes a selectable option list', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false, message: null });

    const loaded = await store.load('pypa/sampleproject');

    expect(loaded).toBe(true);
    expect(loadRepository).toHaveBeenCalledWith(
      'pypa/sampleproject',
      null,
      expect.any(AbortSignal),
      null,
    );
    expect(store.state()).toBe('ready');
    expect(store.files()).toHaveLength(3);
    expect(store.options()[0]).toEqual({ value: 'src/sample.py', label: 'src/sample.py · 2.0 KB' });
    expect(store.canSubmit()).toBe(false);

    store.select('src/sample.py');
    expect(store.selectedFile()?.source_code).toBe('print("sample")');
    expect(store.canSubmit()).toBe(true);
  });

  it('forwards the language filter to the repository load', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false });

    await store.load('owner/advpl', 'main', 'advpl');

    expect(loadRepository).toHaveBeenCalledWith(
      'owner/advpl',
      'main',
      expect.any(AbortSignal),
      'advpl',
    );
  });

  it('exposes languages, filters the list and clears a hidden selection', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false });
    await store.load('owner/mixed');
    store.select('src/sample.py');

    expect(store.availableLanguages()).toEqual(['python', 'advpl']);
    expect(store.languageOptions()).toEqual([
      { value: 'all', label: 'Todas as linguagens' },
      { value: 'python', label: 'Python' },
      { value: 'advpl', label: 'ADVPL' },
    ]);

    store.setLanguageFilter('advpl');

    expect(store.filteredFiles().map((file) => file.path)).toEqual(['src/financeiro.prg']);
    expect(store.selectedPath()).toBe('');
    expect(store.canSubmit()).toBe(false);

    store.select('src/financeiro.prg');
    expect(store.canSubmit()).toBe(true);
    expect(store.options()).toEqual([
      { value: 'src/financeiro.prg', label: 'src/financeiro.prg · 1.0 KB' },
    ]);
  });

  it('keeps the selection when the filter still includes the file', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false });
    await store.load('owner/mixed');
    store.select('src/sample.py');

    store.setLanguageFilter('python');

    expect(store.selectedPath()).toBe('src/sample.py');
    expect(store.canSubmit()).toBe(true);
  });

  it('surfaces paths, tree completeness, relations and the Protheus metadata', async () => {
    loadRepository.mockResolvedValue({
      files: FILES,
      truncated: true,
      paths: ['src/sample.py', 'src/financeiro.prg', 'apps.json'],
      tree_complete: false,
      relations: RELATIONS,
      protheus: RELATIONS.protheus?.apps_json,
    });

    await store.load('owner/large-repo');

    expect(store.truncated()).toBe(true);
    expect(store.treeComplete()).toBe(false);
    expect(store.paths()).toHaveLength(3);
    expect(store.relationsSummary()).toEqual({
      resolved: 2,
      missing: 1,
      external: 0,
      unknown: 3,
    });
    expect(store.hasAppsJson()).toBe(true);
    expect(store.protheus()?.path).toBe('apps.json');
  });

  it('offers only eligible files and enforces the three-file batch limit', async () => {
    loadRepository.mockResolvedValue({
      files: [
        ...FILES,
        {
          path: 'src/fourth.py',
          size: 8,
          source_code: 'x = 1\n',
          language: 'python',
        },
        {
          path: '.env',
          size: 20,
          source_code: 'TOKEN=secret',
          language: 'unknown',
        },
        {
          path: 'docs/README.md',
          size: 10,
          source_code: '# docs',
          language: 'unknown',
        },
      ],
      truncated: false,
    });
    await store.load('owner/mixed');

    expect(store.correctionCandidates().map((file) => file.path)).toEqual([
      'src/sample.py',
      'tests/test_sample.py',
      'src/financeiro.prg',
      'src/fourth.py',
    ]);
    expect(store.hiddenCorrectionFileCount()).toBe(2);

    expect(store.toggleCorrectionFile('.env')).toBe('unavailable');
    expect(store.toggleCorrectionFile('src/sample.py')).toBe('added');
    expect(store.toggleCorrectionFile('tests/test_sample.py')).toBe('added');
    expect(store.toggleCorrectionFile('src/financeiro.prg')).toBe('added');
    expect(store.correctionSelectionCount()).toBe(3);
    expect(store.correctionSelectionLimitReached()).toBe(true);
    expect(store.toggleCorrectionFile('src/fourth.py')).toBe('limit');
    expect(store.correctionSelectionCount()).toBe(3);

    expect(store.toggleCorrectionFile('src/sample.py')).toBe('removed');
    expect(store.correctionSelectionCount()).toBe(2);
    expect(store.toggleCorrectionFile('src/fourth.py')).toBe('added');
    expect(store.correctionSelection().map((file) => file.path)).toEqual([
      'tests/test_sample.py',
      'src/financeiro.prg',
      'src/fourth.py',
    ]);
  });

  it('records the analyzed issue count and clears it with a new load', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false });
    await store.load('owner/mixed');

    expect(store.issueCountFor('src/sample.py')).toBeNull();
    store.recordIssueCount('src/sample.py', 2);
    expect(store.issueCountFor('src/sample.py')).toBe(2);

    store.toggleCorrectionFile('src/sample.py');
    expect(store.correctionSelectionCount()).toBe(1);

    await store.load('owner/mixed');
    expect(store.issueCountFor('src/sample.py')).toBeNull();
    expect(store.correctionSelectionCount()).toBe(0);
  });

  it('reports an empty repository with the API message and no selectable files', async () => {
    loadRepository.mockResolvedValue({
      files: [],
      truncated: false,
      message: 'No eligible files were found in this repository.',
    });

    const loaded = await store.load('owner/docs-only');

    expect(loaded).toBe(false);
    expect(store.state()).toBe('empty');
    expect(store.files()).toHaveLength(0);
    expect(store.options()).toHaveLength(0);
    expect(store.canSubmit()).toBe(false);
    expect(store.message()).toBe('No eligible files were found in this repository.');
  });

  it('falls back to a multi-language empty message when the API sends none', async () => {
    loadRepository.mockResolvedValue({ files: [], truncated: false, message: null });

    await store.load('owner/empty');

    expect(store.state()).toBe('empty');
    expect(store.message()).toContain('ADVPL');
    expect(store.message()).toContain('JavaScript');
  });

  it('surfaces a truncated load without dropping the returned files', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: true });

    await store.load('owner/large-repo', 'main');

    expect(store.state()).toBe('ready');
    expect(store.truncated()).toBe(true);
    expect(store.files()).toHaveLength(3);
    expect(loadRepository).toHaveBeenCalledWith(
      'owner/large-repo',
      'main',
      expect.any(AbortSignal),
      null,
    );
  });

  it('clears the previous selection when a new load fails', async () => {
    loadRepository.mockResolvedValueOnce({ files: FILES, truncated: false });
    await store.load('owner/first');
    store.select('src/sample.py');
    expect(store.canSubmit()).toBe(true);

    loadRepository.mockRejectedValueOnce(new ApiError('not-found', 'Repositório não encontrado.'));

    await store.load('owner/missing');

    expect(store.state()).toBe('error');
    expect(store.files()).toHaveLength(0);
    expect(store.selectedPath()).toBe('');
    expect(store.canSubmit()).toBe(false);
    expect(store.error()).toBe('Repositório não encontrado.');
  });

  it('does not call the API for an empty reference and clears the list', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: false });
    await store.load('owner/first');

    const loaded = await store.load('   ');

    expect(loaded).toBe(false);
    expect(loadRepository).toHaveBeenCalledTimes(1);
    expect(store.state()).toBe('error');
    expect(store.files()).toHaveLength(0);
    expect(store.error()).toContain('Informe a URL');
  });
});
