import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../api/api-client';
import { ApiError } from '../api/api-error.mapper';
import { RepositoryFile } from '../api/api.types';
import { RepositoryStore } from './repository-store';

const FILES: readonly RepositoryFile[] = [
  { path: 'src/sample.py', size: 2048, source_code: 'print("sample")' },
  { path: 'tests/test_sample.py', size: 512, source_code: 'def test_sample(): pass' },
];

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
    );
    expect(store.state()).toBe('ready');
    expect(store.files()).toHaveLength(2);
    expect(store.options()[0]).toEqual({ value: 'src/sample.py', label: 'src/sample.py · 2.0 KB' });
    expect(store.canSubmit()).toBe(false);

    store.select('src/sample.py');
    expect(store.selectedFile()?.source_code).toBe('print("sample")');
    expect(store.canSubmit()).toBe(true);
  });

  it('reports an empty repository with the API message and no selectable files', async () => {
    loadRepository.mockResolvedValue({
      files: [],
      truncated: false,
      message: 'No eligible Python files were found in this repository.',
    });

    const loaded = await store.load('owner/docs-only');

    expect(loaded).toBe(false);
    expect(store.state()).toBe('empty');
    expect(store.files()).toHaveLength(0);
    expect(store.options()).toHaveLength(0);
    expect(store.canSubmit()).toBe(false);
    expect(store.message()).toBe('No eligible Python files were found in this repository.');
  });

  it('surfaces a truncated load without dropping the returned files', async () => {
    loadRepository.mockResolvedValue({ files: FILES, truncated: true });

    await store.load('owner/large-repo', 'main');

    expect(store.state()).toBe('ready');
    expect(store.truncated()).toBe(true);
    expect(store.files()).toHaveLength(2);
    expect(loadRepository).toHaveBeenCalledWith(
      'owner/large-repo',
      'main',
      expect.any(AbortSignal),
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
