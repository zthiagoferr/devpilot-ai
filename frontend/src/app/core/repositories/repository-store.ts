import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';

import { ApiClient, isAbortError } from '../api/api-client';
import { isApiError } from '../api/api-error.mapper';
import { RepositoryFile } from '../api/api.types';

export type RepositoryLoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

export interface RepositoryFileOption {
  readonly value: string;
  readonly label: string;
}

const EMPTY_MESSAGE = 'Nenhum arquivo Python elegível foi encontrado neste repositório.';

/**
 * Owns the `POST /repositories/load` lifecycle for the GitHub tab.
 *
 * Rules enforced here (and covered by the tests):
 * - every new load clears the previous file list and selection first, so a
 *   failure can never leave a file from another repository selected;
 * - an empty answer is `empty` (200 + `message`), not an error;
 * - `truncated` is surfaced separately from the file count;
 * - only one request is in flight; a newer load aborts the previous one.
 */
@Injectable({ providedIn: 'root' })
export class RepositoryStore {
  private readonly api = inject(ApiClient);
  private readonly destroyRef = inject(DestroyRef);

  readonly files = signal<readonly RepositoryFile[]>([]);
  readonly state = signal<RepositoryLoadState>('idle');
  readonly truncated = signal(false);
  readonly message = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly selectedPath = signal('');

  readonly isLoading = computed(() => this.state() === 'loading');
  readonly isEmpty = computed(() => this.state() === 'empty');
  readonly hasFiles = computed(() => this.state() === 'ready' && this.files().length > 0);

  readonly options = computed<readonly RepositoryFileOption[]>(() =>
    this.files().map((file) => ({
      value: file.path,
      label: formatFileLabel(file),
    })),
  );

  readonly selectedFile = computed<RepositoryFile | null>(() => {
    const path = this.selectedPath();
    return this.files().find((file) => file.path === path) ?? null;
  });

  readonly canSubmit = computed(
    () => this.hasFiles() && this.selectedPath() !== '' && this.selectedFile() !== null,
  );

  private controller: AbortController | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.controller?.abort());
  }

  async load(repositoryUrl: string, branch?: string | null): Promise<boolean> {
    const reference = repositoryUrl.trim();
    const branchName = (branch ?? '').trim();

    this.controller?.abort();
    this.resetSelection();

    if (reference === '') {
      this.files.set([]);
      this.state.set('error');
      this.error.set('Informe a URL do repositório GitHub.');
      return false;
    }

    const controller = new AbortController();
    this.controller = controller;
    this.state.set('loading');
    this.error.set(null);
    this.message.set(null);
    this.truncated.set(false);

    try {
      const payload = await this.api.loadRepository(
        reference,
        branchName === '' ? null : branchName,
        controller.signal,
      );
      if (controller.signal.aborted) {
        return false;
      }

      this.files.set(payload.files ?? []);
      this.truncated.set(payload.truncated === true);

      if ((payload.files ?? []).length === 0) {
        this.message.set(payload.message ?? EMPTY_MESSAGE);
        this.state.set('empty');
        this.selectedPath.set('');
        return false;
      }

      this.message.set(null);
      this.state.set('ready');
      return true;
    } catch (error) {
      if (isAbortError(error) || controller.signal.aborted) {
        return false;
      }

      this.files.set([]);
      this.truncated.set(false);
      this.message.set(null);
      this.selectedPath.set('');
      this.state.set('error');
      this.error.set(
        isApiError(error)
          ? error.message
          : 'Não foi possível carregar os arquivos do repositório. Tente novamente.',
      );
      return false;
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }

  select(path: string): void {
    this.selectedPath.set(path);
  }

  clear(): void {
    this.controller?.abort();
    this.controller = null;
    this.files.set([]);
    this.state.set('idle');
    this.truncated.set(false);
    this.message.set(null);
    this.error.set(null);
    this.selectedPath.set('');
  }

  /** Clears the previous list and selection at the start of every load. */
  private resetSelection(): void {
    this.selectedPath.set('');
    this.files.set([]);
    this.truncated.set(false);
    this.message.set(null);
    this.error.set(null);
  }
}

export function formatFileLabel(file: RepositoryFile): string {
  const size = file.size;
  if (typeof size !== 'number' || !Number.isFinite(size) || size < 0) {
    return file.path;
  }
  return `${file.path} · ${formatBytes(size)}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
