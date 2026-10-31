import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { ApiClient, isAbortError } from '../../../core/api/api-client';
import { analysisSuccessMessage } from '../../../core/api/analysis-summary';
import { isApiError } from '../../../core/api/api-error.mapper';
import {
  Analysis,
  AnalysisIssue,
  AnalysisLanguage,
  Correction,
  CorrectionBatchCreate,
  CorrectionBatchResponse,
  CorrectionRepositoryContext,
  RepositoryContext,
  RepositoryFile,
} from '../../../core/api/api.types';
import {
  MAX_CORRECTION_FILES,
  RepositoryStore,
  formatBytes,
  languageName,
  sourceByteLength,
} from '../../../core/repositories/repository-store';
import { repositoryEmptyMessagePtBr } from '../../../shared/utils/pt-br-messages';
import { BadgeComponent } from '../../../shared/components/badge/badge.component';
import { ButtonComponent } from '../../../shared/components/button/button.component';
import {
  CorrectionBatchPanelComponent,
  CorrectionBatchSource,
} from '../../../shared/components/correction-batch-panel/correction-batch-panel.component';
import { toIssueRef } from '../../../shared/components/correction-panel/correction-issue-ref';
import { IconComponent } from '../../../shared/components/icon/icon.component';
import {
  InlineStatusComponent,
  InlineStatusTone,
} from '../../../shared/components/inline-status/inline-status.component';
import { InputComponent } from '../../../shared/components/input/input.component';
import { LanguageSelectComponent } from '../../../shared/components/language-select/language-select.component';
import { SelectComponent } from '../../../shared/components/select/select.component';

interface FormStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

const MAX_PROJECT_NAME = 120;

/**
 * GitHub repository tab: load the analyzable files of a public repository,
 * filter them by language, pick one and submit it to `POST /analyses` with its
 * origin and the deterministic repository context.
 *
 * A load failure (or a new load/language change) clears the previous
 * selection, so a file from one repository can never be submitted together
 * with another repository URL.
 */
@Component({
  selector: 'app-repository-analysis',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BadgeComponent,
    ButtonComponent,
    CorrectionBatchPanelComponent,
    IconComponent,
    InlineStatusComponent,
    InputComponent,
    LanguageSelectComponent,
    SelectComponent,
  ],
  templateUrl: './repository-analysis.component.html',
  styleUrl: './repository-analysis.component.css',
})
export class RepositoryAnalysisComponent {
  readonly analyzed = output<Analysis>();
  /** Emitted when a new analysis starts, before the API call resolves. */
  readonly started = output<void>();
  /** Emitted when the form is cleared, so the shell can drop its result. */
  readonly cleared = output<void>();
  /** Emitted when a decision needs an authenticated session. */
  readonly loginRequested = output<void>();
  readonly decided = output<Correction>();
  /** Session state from the shell; controls whether `analysis_id` is sent. */
  readonly authenticated = input(false);

  private readonly api = inject(ApiClient);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly store = inject(RepositoryStore);

  protected readonly projectName = signal('');
  protected readonly repositoryUrl = signal('');
  protected readonly branch = signal('');
  protected readonly language = signal<AnalysisLanguage>('auto');
  protected readonly protheusVersion = signal('');
  protected readonly submitted = signal(false);
  protected readonly submitting = signal(false);
  protected readonly submitStatus = signal<FormStatus | null>(null);

  /** Last analysis of the repository tab; source of the known issue counts. */
  private readonly lastAnalysis = signal<Analysis | null>(null);
  private readonly lastAnalyzedPath = signal('');
  /** Bumped when the form is cleared so a late batch response is discarded. */
  private batchGeneration = 0;
  protected readonly batchResponse = signal<CorrectionBatchResponse | null>(null);
  protected readonly batchRequesting = signal(false);
  protected readonly batchStatus = signal<FormStatus | null>(null);
  protected readonly batchSelectionNotice = signal<string | null>(null);

  protected readonly loadStatus = computed<FormStatus | null>(() => {
    switch (this.store.state()) {
      case 'loading':
        return { tone: 'loading', message: 'Carregando arquivos do repositório…' };
      case 'error':
        return {
          tone: 'error',
          message: this.store.error() ?? 'Não foi possível carregar o repositório.',
        };
      case 'empty':
        return {
          tone: 'warning',
          message: repositoryEmptyMessagePtBr(this.store.message()),
        };
      case 'ready': {
        const count = this.store.files().length;
        return {
          tone: 'success',
          message: count === 1 ? '1 arquivo carregado.' : `${count} arquivos carregados.`,
        };
      }
      default:
        return null;
    }
  });

  protected readonly showTruncated = computed(
    () => this.store.state() === 'ready' && this.store.truncated(),
  );

  protected readonly fileCount = computed(() => this.store.files().length);

  /**
   * Exact `repository_context` sent with the analysis: the files already
   * loaded (with source and detected language) plus the tree metadata.
   */
  protected readonly repositoryContext = computed<RepositoryContext | null>(() => {
    if (this.store.state() !== 'ready') {
      return null;
    }
    const files = this.store
      .files()
      .filter((file) => (file.source_code ?? '').trim() !== '')
      .map((file) => ({
        path: file.path,
        source_code: file.source_code ?? '',
        ...(file.language ? { language: file.language } : {}),
      }));
    if (files.length === 0) {
      return null;
    }
    return {
      files,
      paths: [...this.store.paths()],
      tree_complete: this.store.treeComplete(),
      truncated: this.store.truncated(),
    };
  });

  protected readonly contextFileCount = computed(() => this.repositoryContext()?.files.length ?? 0);

  protected readonly correctionCandidates = computed(() => this.store.correctionCandidates());

  protected readonly correctionSelectionCount = computed(() =>
    this.store.correctionSelectionCount(),
  );

  protected readonly maxCorrectionFiles = MAX_CORRECTION_FILES;

  protected readonly correctionSelectionBytes = computed(() =>
    this.store
      .correctionSelection()
      .reduce((total, file) => total + sourceByteLength(file.source_code ?? ''), 0),
  );

  protected readonly correctionSelectionBytesLabel = computed(() =>
    formatBytes(this.correctionSelectionBytes()),
  );

  protected readonly correctionBatchDisabled = computed(
    () =>
      this.correctionSelectionCount() === 0 ||
      this.correctionSelectionCount() > MAX_CORRECTION_FILES ||
      this.batchRequesting() ||
      this.store.isLoading() ||
      this.submitting(),
  );

  protected readonly correctionProgressMessage = computed(() => {
    const count = this.correctionSelectionCount();
    // "90 segundos" mirrors the backend batch budget
    // (`CORRECTION_BATCH_BUDGET_SECONDS`, default 90).
    return `Processando ${count} ${count === 1 ? 'arquivo' : 'arquivos'} com IA. Isso pode levar até 90 segundos.`;
  });

  /** Repository context shared by every file of the batch. */
  protected readonly correctionRepositoryContext = computed<CorrectionRepositoryContext>(() => ({
    paths: [...this.store.paths()],
    tree_complete: this.store.treeComplete(),
    truncated: this.store.truncated(),
  }));

  /** Every eligible source, so a failed item can be retried after a new selection. */
  protected readonly correctionSources = computed<Readonly<Record<string, CorrectionBatchSource>>>(
    () => {
      const sources: Record<string, CorrectionBatchSource> = {};
      for (const file of this.store.correctionCandidates()) {
        sources[file.path] = {
          source_code: file.source_code ?? '',
          issues: this.knownIssues(file.path),
        };
      }
      return sources;
    },
  );

  protected readonly batchAnalysisId = computed(() =>
    this.authenticated() ? (this.lastAnalysis()?.id ?? null) : null,
  );

  protected readonly projectNameError = computed(() => {
    if (!this.submitted()) {
      return '';
    }
    const value = this.projectName().trim();
    if (value === '') {
      return 'Informe um nome para o projeto.';
    }
    if (value.length > MAX_PROJECT_NAME) {
      return 'Use no máximo 120 caracteres.';
    }
    return '';
  });

  protected readonly repositoryUrlError = computed(() => {
    if (!this.submitted()) {
      return '';
    }
    return this.repositoryUrl().trim() === '' ? 'Informe a URL do repositório GitHub.' : '';
  });

  protected readonly fileError = computed(() => {
    if (!this.submitted()) {
      return '';
    }
    if (!this.store.hasFiles()) {
      return 'Carregue um repositório e selecione um arquivo.';
    }
    return this.store.selectedPath() === '' ? 'Selecione um arquivo do repositório.' : '';
  });

  protected readonly selectPlaceholder = computed(() => {
    switch (this.store.state()) {
      case 'empty':
        return 'Nenhum arquivo elegível encontrado neste repositório';
      case 'ready':
        return 'Selecione um arquivo';
      case 'loading':
        return 'Carregando arquivos…';
      default:
        return 'Informe um repositório para carregar os arquivos';
    }
  });

  protected updateRepositoryUrl(value: string): void {
    this.repositoryUrl.set(value);
    this.clearLoadedFiles();
  }

  protected updateBranch(value: string): void {
    this.branch.set(value);
    this.clearLoadedFiles();
  }

  protected updateLanguage(value: AnalysisLanguage): void {
    this.language.set(value);
    if (value !== 'advpl') {
      this.protheusVersion.set('');
    }
    this.clearLoadedFiles();
  }

  protected updateProtheusVersion(value: string): void {
    this.protheusVersion.set(value);
  }

  protected fileLanguage(file: RepositoryFile): string {
    return languageName((file.language ?? '').trim().toLowerCase());
  }

  protected fileSize(file: RepositoryFile): string {
    return typeof file.size === 'number' ? formatBytes(file.size) : '';
  }

  protected async loadFiles(): Promise<void> {
    this.submitted.set(false);
    this.submitStatus.set(null);
    this.clearBatch();
    await this.store.load(this.repositoryUrl(), this.branch(), this.language());
  }

  protected issueCountLabel(file: RepositoryFile): string {
    const count = this.store.issueCountFor(file.path);
    if (count === null) {
      return 'problemas não analisados';
    }
    return `${count} ${count === 1 ? 'problema' : 'problemas'} conhecidos`;
  }

  protected toggleBatchFile(path: string): void {
    const result = this.store.toggleCorrectionFile(path);
    if (result === 'limit') {
      this.batchSelectionNotice.set(
        `Máx. ${MAX_CORRECTION_FILES} arquivos por lote. Desmarque um arquivo para escolher outro.`,
      );
      return;
    }
    this.batchSelectionNotice.set(null);
  }

  protected removeBatchFile(path: string): void {
    this.store.toggleCorrectionFile(path);
    this.batchSelectionNotice.set(null);
  }

  protected async runCorrectionBatch(): Promise<void> {
    if (this.batchRequesting()) {
      return;
    }
    const count = this.correctionSelectionCount();
    if (count === 0) {
      this.batchSelectionNotice.set('Selecione pelo menos um arquivo para corrigir.');
      return;
    }
    if (count > MAX_CORRECTION_FILES) {
      this.batchSelectionNotice.set(`Máx. ${MAX_CORRECTION_FILES} arquivos por lote.`);
      return;
    }

    this.batchRequesting.set(true);
    this.batchSelectionNotice.set(null);
    this.batchResponse.set(null);
    this.batchStatus.set({ tone: 'loading', message: this.correctionProgressMessage() });
    const generation = ++this.batchGeneration;

    try {
      const response = await this.api.createCorrectionBatch(this.correctionBatchPayload());
      if (generation !== this.batchGeneration) {
        return;
      }
      this.batchResponse.set(response);
      this.store.clearCorrectionSelection();
      this.batchStatus.set({
        tone: response.partial ? 'warning' : 'success',
        message: response.partial
          ? 'Lote concluído com falhas ou arquivos pulados. Revise cada item abaixo.'
          : 'Lote concluído. Revise e decida cada arquivo individualmente.',
      });
    } catch (error) {
      if (isAbortError(error) || generation !== this.batchGeneration) {
        return;
      }
      this.batchStatus.set({
        tone: 'error',
        message: correctionBatchErrorMessage(error),
      });
    } finally {
      if (generation === this.batchGeneration) {
        this.batchRequesting.set(false);
      }
    }
  }

  /** Targets known for a path; only the file just analyzed has any. */
  private knownIssues(path: string): readonly AnalysisIssue[] {
    if (this.lastAnalyzedPath() !== path) {
      return [];
    }
    const analysis = this.lastAnalysis();
    if (analysis === null) {
      return [];
    }
    return (analysis.result?.issues ?? []).filter(
      (issue) => issue.file === null || issue.file === undefined || issue.file === path,
    );
  }

  private correctionBatchPayload(): CorrectionBatchCreate {
    const analysisId = this.batchAnalysisId();
    const language = this.language();
    const protheusVersion = language === 'advpl' ? this.protheusVersion().trim() : '';
    const files = this.store.correctionSelection().map((file) => {
      const issues = this.knownIssues(file.path);
      return {
        path: file.path,
        source_code: file.source_code ?? '',
        ...(issues.length === 0 ? {} : { issues: issues.map(toIssueRef) }),
      };
    });

    return {
      ...(analysisId === null ? {} : { analysis_id: analysisId }),
      files,
      ...(language === 'auto' ? {} : { language }),
      ...(protheusVersion === '' ? {} : { protheus_version: protheusVersion }),
      repository_context: this.correctionRepositoryContext(),
    };
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.submitting() || this.store.isLoading()) {
      return;
    }

    this.submitted.set(true);
    this.submitStatus.set(null);
    this.clearBatch();

    const file = this.store.selectedFile();
    if (this.projectNameError() !== '' || this.repositoryUrlError() !== '' || file === null) {
      const message =
        file === null && this.store.hasFiles()
          ? 'Selecione um arquivo do repositório.'
          : 'Corrija os campos destacados e tente novamente.';
      this.submitStatus.set({ tone: 'warning', message });
      this.focusFirstInvalid();
      return;
    }

    const source = file.source_code ?? '';
    if (source.trim() === '') {
      this.submitStatus.set({
        tone: 'error',
        message: 'O arquivo selecionado não tem conteúdo disponível. Escolha outro arquivo.',
      });
      return;
    }

    this.submitting.set(true);
    this.started.emit();
    this.submitStatus.set({
      tone: 'loading',
      message: 'Analisando o arquivo selecionado. Isso pode levar alguns segundos.',
    });

    const branchName = this.branch().trim();
    const language = this.language();
    const protheusVersion = language === 'advpl' ? this.protheusVersion().trim() : '';
    const context = this.repositoryContext();
    try {
      const analysis = await this.api.createAnalysis({
        task: 'code',
        project_name: this.projectName().trim(),
        source_code: source,
        repository_url: this.repositoryUrl().trim(),
        file_path: file.path,
        language,
        ...(branchName === '' ? {} : { branch: branchName }),
        ...(protheusVersion === '' ? {} : { protheus_version: protheusVersion }),
        ...(context === null ? {} : { repository_context: context }),
      });

      this.analyzed.emit(analysis);
      this.lastAnalysis.set(analysis);
      this.lastAnalyzedPath.set(file.path);
      this.store.recordIssueCount(file.path, this.knownIssues(file.path).length);
      this.submitStatus.set({
        tone: analysis.status === 'completed' ? 'success' : 'warning',
        message: analysisSuccessMessage(analysis),
      });
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
      this.submitStatus.set({
        tone: isApiError(error) && error.kind === 'validation' ? 'warning' : 'error',
        message: isApiError(error)
          ? error.message
          : 'Não foi possível concluir a análise. Tente novamente.',
      });
    } finally {
      this.submitting.set(false);
    }
  }

  protected clear(): void {
    this.projectName.set('');
    this.repositoryUrl.set('');
    this.branch.set('');
    this.language.set('auto');
    this.protheusVersion.set('');
    this.submitted.set(false);
    this.submitStatus.set(null);
    this.clearBatch();
    this.store.clear();
    this.cleared.emit();
  }

  private clearLoadedFiles(): void {
    if (this.store.state() !== 'idle') {
      this.clearBatch();
      this.store.clear();
    }
  }

  private clearBatch(): void {
    this.batchGeneration += 1;
    this.lastAnalysis.set(null);
    this.lastAnalyzedPath.set('');
    this.batchResponse.set(null);
    this.batchRequesting.set(false);
    this.batchStatus.set(null);
    this.batchSelectionNotice.set(null);
    this.store.clearCorrectionSelection();
  }

  private focusFirstInvalid(): void {
    setTimeout(() => {
      this.host.nativeElement.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }, 0);
  }
}

function correctionBatchErrorMessage(error: unknown): string {
  if (!isApiError(error)) {
    return 'Não foi possível corrigir os arquivos selecionados. Tente novamente.';
  }

  switch (error.status) {
    case 422:
      return 'O lote de correção é inválido. Selecione no máximo 3 arquivos compatíveis, com caminhos relativos ao repositório.';
    case 503:
      return 'A correção de IA não está configurada no servidor. Configure o provedor de LLM e tente novamente.';
    case 404:
      return 'A análise vinculada ao lote não foi encontrada. Faça uma nova análise ou saia da conta para corrigir sem vínculo.';
    case 429:
      return error.retryAfterSeconds !== null && error.retryAfterSeconds > 0
        ? `Muitas solicitações de correção. Aguarde ${error.retryAfterSeconds} s e tente novamente.`
        : 'Muitas solicitações de correção. Aguarde alguns instantes e tente novamente.';
    default:
      return error.message;
  }
}
