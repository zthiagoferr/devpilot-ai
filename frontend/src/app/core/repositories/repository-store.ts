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

/**
 * Maximum number of files the batch correction endpoint accepts.
 * Mirrors the backend setting `CORRECTION_BATCH_MAX_FILES` (default 3); keep
 * both in sync when the server limit changes.
 */
export const MAX_CORRECTION_FILES = 3;

/**
 * Mirrors the backend per-file source limit used by batch corrections
 * (`CORRECTION_MAX_SOURCE_BYTES`, default 200000 bytes).
 */
export const MAX_CORRECTION_SOURCE_BYTES = 200_000;

/** Extensions with a deterministic backend validator. */
const SUPPORTED_SOURCE_EXTENSIONS: ReadonlySet<string> = new Set([
  '.py',
  '.pyi',
  '.prw',
  '.prg',
  '.ch',
  '.html',
  '.htm',
  '.css',
  '.js',
  '.mjs',
  '.cjs',
]);

/** Credential-bearing names that must never be sent to the AI provider. */
const SENSITIVE_FILENAMES: ReadonlySet<string> = new Set([
  '.env',
  '.netrc',
  '.npmrc',
  '.pgpass',
  'credentials',
  'id_dsa',
  'id_ecdsa',
  'id_ed25519',
  'id_rsa',
]);

const SENSITIVE_PREFIXES: readonly string[] = [
  '.env.',
  'credentials.',
  'id_dsa',
  'id_ecdsa',
  'id_ed25519',
  'id_rsa',
];

const SENSITIVE_SUFFIXES: readonly string[] = ['.jks', '.key', '.keystore', '.p12', '.pem', '.pfx'];

const SENSITIVE_DIRECTORIES: ReadonlySet<string> = new Set([
  '.aws',
  '.git',
  '.gnupg',
  '.ssh',
  'node_modules',
]);

const ALLOWED_EXAMPLE_FILES: ReadonlySet<string> = new Set([
  '.env.example',
  '.env.sample',
  '.env.template',
]);

/** Outcome of a checkbox toggle in the batch selection list. */
export type CorrectionSelectionResult = 'added' | 'removed' | 'limit' | 'unavailable';

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
  /** Issue count of the file just analyzed, keyed by repository path. */
  readonly issueCounts = signal<Readonly<Record<string, number>>>({});
  /** Paths checked for the batch correction, preserving the click order. */
  readonly selectedCorrectionPaths = signal<readonly string[]>([]);

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

  /** Files the client can submit to the batch endpoint. */
  readonly correctionCandidates = computed<readonly RepositoryFile[]>(() =>
    this.files().filter((file) => isCorrectionEligible(file)),
  );

  readonly hiddenCorrectionFileCount = computed(
    () => this.files().length - this.correctionCandidates().length,
  );

  readonly correctionSelection = computed<readonly RepositoryFile[]>(() => {
    const selected = new Set(this.selectedCorrectionPaths());
    return this.correctionCandidates().filter((file) => selected.has(file.path));
  });

  readonly correctionSelectionCount = computed(() => this.correctionSelection().length);

  readonly correctionSelectionLimitReached = computed(
    () => this.correctionSelectionCount() >= MAX_CORRECTION_FILES,
  );

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

  /** Records how many findings the last analysis reported for one path. */
  recordIssueCount(path: string, count: number): void {
    if (path === '' || !Number.isFinite(count) || count < 0) {
      return;
    }
    this.issueCounts.update((current) => ({ ...current, [path]: Math.round(count) }));
  }

  /** Known issue count for a path, or `null` when it was never analyzed. */
  issueCountFor(path: string): number | null {
    return this.issueCounts()[path] ?? null;
  }

  isCorrectionSelected(path: string): boolean {
    return this.selectedCorrectionPaths().includes(path);
  }

  /**
   * Checks/unchecks one file of the batch.
   *
   * The limit is enforced here (not only in the template) so no caller can
   * build a payload above the backend maximum. A path that is not eligible can
   * never be selected.
   */
  toggleCorrectionFile(path: string): CorrectionSelectionResult {
    const current = this.selectedCorrectionPaths();
    if (current.includes(path)) {
      this.selectedCorrectionPaths.set(current.filter((item) => item !== path));
      return 'removed';
    }
    if (!this.correctionCandidates().some((file) => file.path === path)) {
      return 'unavailable';
    }
    if (current.length >= MAX_CORRECTION_FILES) {
      return 'limit';
    }
    this.selectedCorrectionPaths.set([...current, path]);
    return 'added';
  }

  clearCorrectionSelection(): void {
    this.selectedCorrectionPaths.set([]);
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
    this.issueCounts.set({});
    this.selectedCorrectionPaths.set([]);
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
    this.issueCounts.set({});
    this.selectedCorrectionPaths.set([]);
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

/** Lowercase extension including the leading dot, or `''`. */
export function sourceExtension(path: string): string {
  const name = path.slice(path.lastIndexOf('/') + 1).toLowerCase();
  const index = name.lastIndexOf('.');
  return index <= 0 ? '' : name.slice(index);
}

/** Whether the backend has a deterministic validator for this path. */
export function isSupportedSourcePath(path: string): boolean {
  return SUPPORTED_SOURCE_EXTENSIONS.has(sourceExtension(path));
}

/**
 * Whether a path is credential-bearing.
 *
 * Mirrors the backend lexical check so the UI never offers a secret file for
 * correction. Example env files are documentation, not secrets.
 */
export function isSensitiveRepositoryPath(path: string): boolean {
  const normalized = path.replace(/\\/g, '/').toLowerCase();
  const name = normalized.slice(normalized.lastIndexOf('/') + 1);
  if (ALLOWED_EXAMPLE_FILES.has(name)) {
    return false;
  }
  const directories = normalized.split('/').slice(0, -1);
  if (directories.some((part) => SENSITIVE_DIRECTORIES.has(part))) {
    return true;
  }
  if (SENSITIVE_FILENAMES.has(name)) {
    return true;
  }
  if (SENSITIVE_PREFIXES.some((prefix) => name.startsWith(prefix))) {
    return true;
  }
  return SENSITIVE_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

/** UTF-8 byte length of a source string. */
export function sourceByteLength(source: string): number {
  return new TextEncoder().encode(source).length;
}

/** Whether a loaded file can be sent to the batch correction endpoint. */
export function isCorrectionEligible(file: RepositoryFile): boolean {
  const source = file.source_code ?? '';
  if (source.trim() === '') {
    return false;
  }
  if (isSensitiveRepositoryPath(file.path) || !isSupportedSourcePath(file.path)) {
    return false;
  }
  return sourceByteLength(source) <= MAX_CORRECTION_SOURCE_BYTES;
}

function languageRank(language: string): number {
  const index = LANGUAGE_ORDER.indexOf(language);
  return index === -1 ? LANGUAGE_ORDER.length : index;
}
