import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';

import { ApiClient, isAbortError } from '../api/api-client';
import { isApiError } from '../api/api-error.mapper';
import { AnalysisLanguage, ProtheusAppsJson, Relations, RepositoryFile } from '../api/api.types';

export type RepositoryLoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

export interface RepositoryFileOption {
  readonly value: string;
  readonly label: string;
}

export interface RepositoryLanguageOption {
  readonly value: string;
  readonly label: string;
}

const EMPTY_MESSAGE =
  'Nenhum arquivo Python, ADVPL, HTML5, CSS3 ou JavaScript elegível foi encontrado neste repositório.';

const LANGUAGE_ORDER: readonly string[] = ['python', 'advpl', 'html', 'css', 'javascript'];

const LANGUAGE_NAMES: Readonly<Record<string, string>> = {
  python: 'Python',
  advpl: 'ADVPL',
  html: 'HTML5',
  css: 'CSS3',
  javascript: 'JavaScript',
  unknown: 'Desconhecida',
};

/**
 * Owns the `POST /repositories/load` lifecycle for the GitHub tab.
 *
 * Rules enforced here (and covered by the tests):
 * - every new load clears the previous file list and selection first, so a
 *   failure can never leave a file from another repository selected;
 * - an empty answer is `empty` (200 + `message`), not an error, and the API
 *   message is preferred over the local fallback;
 * - `truncated`, `tree_complete`, `relations` and the Protheus metadata are
 *   surfaced without ever blocking a load;
 * - the language filter only affects the UI list/selection, never the API;
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
  readonly paths = signal<readonly string[]>([]);
  readonly treeComplete = signal(false);
  readonly relations = signal<Relations | null>(null);
  readonly protheus = signal<ProtheusAppsJson | null>(null);
  readonly languageFilter = signal('all');

  readonly isLoading = computed(() => this.state() === 'loading');
  readonly isEmpty = computed(() => this.state() === 'empty');
  readonly hasFiles = computed(() => this.state() === 'ready' && this.files().length > 0);

  readonly availableLanguages = computed<readonly string[]>(() => {
    const found = new Set<string>();
    for (const file of this.files()) {
      const language = (file.language ?? '').trim().toLowerCase();
      if (language !== '') {
        found.add(language);
      }
    }
    return [...found].sort((left, right) => languageRank(left) - languageRank(right));
  });

  readonly languageOptions = computed<readonly RepositoryLanguageOption[]>(() => [
    { value: 'all', label: 'Todas as linguagens' },
    ...this.availableLanguages().map((language) => ({
      value: language,
      label: languageName(language),
    })),
  ]);

  readonly filteredFiles = computed<readonly RepositoryFile[]>(() => {
    const filter = this.languageFilter();
    if (filter === 'all') {
      return this.files();
    }
    return this.files().filter((file) => (file.language ?? '').trim().toLowerCase() === filter);
  });

  readonly filteredCount = computed(() => this.filteredFiles().length);

  readonly hasAppsJson = computed(() => {
    const appsJson = this.protheus() ?? this.relations()?.protheus?.apps_json ?? null;
    return appsJson?.present === true || (appsJson?.path ?? '') !== '';
  });

  readonly relationsSummary = computed(() => this.relations()?.summary ?? null);

  readonly options = computed<readonly RepositoryFileOption[]>(() =>
    this.filteredFiles().map((file) => ({
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

  async load(
    repositoryUrl: string,
    branch?: string | null,
    language?: AnalysisLanguage | null,
  ): Promise<boolean> {
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

    try {
      const payload = await this.api.loadRepository(
        reference,
        branchName === '' ? null : branchName,
        controller.signal,
        language ?? null,
      );
      if (controller.signal.aborted) {
        return false;
      }

      const files = payload.files ?? [];
      this.files.set(files);
      this.truncated.set(payload.truncated === true);
      this.paths.set(payload.paths ?? []);
      this.treeComplete.set(payload.tree_complete === true);
      this.relations.set(payload.relations ?? null);
      this.protheus.set(payload.protheus ?? null);

      if (files.length === 0) {
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
      this.paths.set([]);
      this.treeComplete.set(false);
      this.relations.set(null);
      this.protheus.set(null);
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

  /** Applies the UI-only language filter, clearing a now-hidden selection. */
  setLanguageFilter(language: string): void {
    this.languageFilter.set(language);
    const selected = this.selectedFile();
    if (selected === null) {
      this.selectedPath.set('');
      return;
    }
    const filter = this.languageFilter();
    if (filter !== 'all' && (selected.language ?? '').trim().toLowerCase() !== filter) {
      this.selectedPath.set('');
    }
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
    this.paths.set([]);
    this.treeComplete.set(false);
    this.relations.set(null);
    this.protheus.set(null);
    this.languageFilter.set('all');
  }

  /** Clears the previous list and selection at the start of every load. */
  private resetSelection(): void {
    this.selectedPath.set('');
    this.files.set([]);
    this.truncated.set(false);
    this.message.set(null);
    this.error.set(null);
    this.paths.set([]);
    this.treeComplete.set(false);
    this.relations.set(null);
    this.protheus.set(null);
    this.languageFilter.set('all');
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

export function languageName(language: string): string {
  return LANGUAGE_NAMES[language] ?? 'Desconhecida';
}

function languageRank(language: string): number {
  const index = LANGUAGE_ORDER.indexOf(language);
  return index === -1 ? LANGUAGE_ORDER.length : index;
}
