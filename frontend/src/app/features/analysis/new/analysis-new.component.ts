import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';

import { ApiClient, isAbortError } from '../../../core/api/api-client';
import { analysisSuccessMessage } from '../../../core/api/analysis-summary';
import { isApiError } from '../../../core/api/api-error.mapper';
import { Analysis, AnalysisLanguage } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { LoginPromptService } from '../../../core/auth/login-prompt.service';
import { RepositoryStore } from '../../../core/repositories/repository-store';
import { BadgeComponent } from '../../../shared/components/badge/badge.component';
import { ButtonComponent } from '../../../shared/components/button/button.component';
import { CardComponent } from '../../../shared/components/card/card.component';
import { CoverageSummaryComponent } from '../../../shared/components/coverage-summary/coverage-summary.component';
import { IconComponent } from '../../../shared/components/icon/icon.component';
import {
  InlineStatusComponent,
  InlineStatusTone,
} from '../../../shared/components/inline-status/inline-status.component';
import { InputComponent } from '../../../shared/components/input/input.component';
import { IssueListComponent } from '../../../shared/components/issue-list/issue-list.component';
import { LanguageSelectComponent } from '../../../shared/components/language-select/language-select.component';
import { languageLabel } from '../../../shared/components/language-select/language-options';
import { ScoreRingComponent } from '../../../shared/components/score-ring/score-ring.component';
import { TabItem, TabsComponent } from '../../../shared/components/tabs/tabs.component';
import { TextareaComponent } from '../../../shared/components/textarea/textarea.component';
import {
  STRUCTURAL_SCORE_NOTE,
  analysisSummaryPtBr,
  resolveScoreStatus,
  scoreStatusEmptyLabel,
  scoreStatusNotice,
} from '../../../shared/utils/pt-br-messages';
import { RepositoryAnalysisComponent } from './repository-analysis.component';

const MAX_SOURCE_BYTES = 1_000_000;

interface FormStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

const TABS: readonly TabItem[] = [
  { id: 'paste', label: 'Colar código' },
  { id: 'repository', label: 'Repositório GitHub' },
];

@Component({
  selector: 'app-analysis-new',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CoverageSummaryComponent,
    IconComponent,
    InlineStatusComponent,
    InputComponent,
    IssueListComponent,
    LanguageSelectComponent,
    ScoreRingComponent,
    TabsComponent,
    TextareaComponent,
    RepositoryAnalysisComponent,
  ],
  templateUrl: './analysis-new.component.html',
  styleUrl: './analysis-new.component.css',
  providers: [RepositoryStore],
})
export class AnalysisNewComponent {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly account = inject(AuthService);
  protected readonly login = inject(LoginPromptService);

  protected readonly tabs = TABS;
  protected readonly activeTab = signal('paste');

  protected readonly projectName = signal('');
  protected readonly sourceCode = signal('');
  protected readonly language = signal<AnalysisLanguage>('auto');
  protected readonly protheusVersion = signal('');
  protected readonly projectNameTouched = signal(false);
  protected readonly submitted = signal(false);
  protected readonly loading = signal(false);
  protected readonly fieldErrors = signal<Readonly<Record<string, string>>>({});
  protected readonly status = signal<FormStatus | null>(null);

  // Each tab keeps its own result. Switching tabs only changes which result is
  // visible; it never reuses (or leaks) the result of the other mode and never
  // issues a new API call.
  private readonly pasteResult = signal<Analysis | null>(null);
  private readonly repositoryResult = signal<Analysis | null>(null);
  protected readonly result = computed<Analysis | null>(() =>
    this.activeTab() === 'repository' ? this.repositoryResult() : this.pasteResult(),
  );

  protected readonly authenticated = computed(() => this.account.isAuthenticated());

  protected readonly sourceBytes = computed(() => byteLength(this.sourceCode()));

  protected readonly languageHint = computed(() => {
    const language = this.language();
    return language === 'auto'
      ? 'Detecção automática · até 1 MB'
      : `${languageLabel(language)} · até 1 MB`;
  });

  protected readonly resultLanguageLabel = computed(() => {
    const language = this.result()?.result?.language;
    return language === undefined || language === null || language === ''
      ? null
      : languageLabel(language);
  });

  protected readonly resultConfidence = computed(() => {
    const confidence = this.result()?.result?.confidence;
    return typeof confidence === 'number' && Number.isFinite(confidence)
      ? `${Math.round(confidence * 100)}% de confiança`
      : null;
  });

  protected readonly scoreStatus = computed(() =>
    resolveScoreStatus(
      this.result()?.result?.score_status,
      this.result()?.result?.validation_skipped,
    ),
  );

  protected readonly scoreEmptyLabel = computed(() => scoreStatusEmptyLabel(this.scoreStatus()));

  protected readonly scoreStatusNotice = computed(() => scoreStatusNotice(this.scoreStatus()));

  protected readonly scoreStatusTone = computed<InlineStatusTone>(() =>
    this.scoreStatus() === 'unavailable' ? 'error' : 'warning',
  );

  protected readonly coverage = computed(() => this.result()?.result?.coverage ?? null);

  protected readonly structuralNote = computed(() =>
    this.scoreStatus() === 'evaluated' && this.resultIssues().length === 0
      ? STRUCTURAL_SCORE_NOTE
      : null,
  );

  protected readonly projectNameError = computed(() => {
    const server = this.fieldErrors()['project_name'];
    if (!this.isVisible(this.submitted(), this.projectNameTouched(), server)) {
      return '';
    }
    const value = this.projectName().trim();
    if (value === '') {
      return 'Informe um nome para o projeto.';
    }
    if (value.length > 120) {
      return 'Use no máximo 120 caracteres.';
    }
    return server ?? '';
  });

  protected readonly sourceCodeError = computed(() => {
    const server = this.fieldErrors()['source_code'];
    if (!this.isVisible(this.submitted(), false, server)) {
      return '';
    }
    if (this.sourceCode().trim() === '') {
      return 'Cole o código que deve ser analisado.';
    }
    if (this.sourceBytes() > MAX_SOURCE_BYTES) {
      return 'O código excede 1 MB. Reduza o arquivo e tente novamente.';
    }
    return server ?? '';
  });

  protected readonly resultIssues = computed(() => this.result()?.result?.issues ?? []);
  protected readonly displayScore = computed(() => {
    const status = this.scoreStatus();
    if (status === 'skipped' || status === 'unavailable') {
      return null;
    }
    return this.result()?.result?.score ?? null;
  });
  protected readonly resultSummary = computed(() => {
    const analysis = this.result();
    if (analysis === null) {
      return null;
    }
    if (this.scoreStatus() === 'skipped') {
      return 'Idioma não reconhecido — selecione manualmente. A análise estrutural não foi executada.';
    }
    return analysisSummaryPtBr({
      summary: analysis.result?.summary,
      score: this.displayScore(),
      issueCount: this.resultIssues().length,
      status: analysis.status,
    });
  });

  protected readonly evaluationItems = [
    'Qualidade e legibilidade do código',
    'Cobertura e clareza dos testes',
    'Documentação e próximos passos',
  ];

  private controller: AbortController | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.controller?.abort());
  }

  protected formatBytes(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.loading()) {
      return;
    }

    this.submitted.set(true);
    this.fieldErrors.set({});

    if (this.projectNameError() !== '' || this.sourceCodeError() !== '') {
      this.status.set(null);
      this.focusFirstInvalid();
      return;
    }

    this.loading.set(true);
    this.pasteResult.set(null);
    this.status.set({
      tone: 'loading',
      message: 'Analisando com os agentes. Isso pode levar alguns segundos.',
    });

    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;

    try {
      const language = this.language();
      const protheusVersion = language === 'advpl' ? this.protheusVersion().trim() : '';
      const analysis = await this.api.createAnalysis(
        {
          task: 'code_analysis',
          project_name: this.projectName().trim(),
          source_code: this.sourceCode(),
          language,
          ...(protheusVersion === '' ? {} : { protheus_version: protheusVersion }),
        },
        controller.signal,
      );

      this.pasteResult.set(analysis);
      this.status.set({
        tone: analysis.status === 'completed' ? 'success' : 'warning',
        message: analysisSuccessMessage(analysis),
      });
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }

      if (isApiError(error)) {
        this.fieldErrors.set({ ...error.fieldErrors });
        this.status.set({
          tone: error.kind === 'validation' ? 'warning' : 'error',
          message: error.message,
        });
        if (Object.keys(error.fieldErrors).length > 0) {
          this.focusFirstInvalid();
        }
      } else {
        this.status.set({
          tone: 'error',
          message: 'Não foi possível concluir a análise. Tente novamente.',
        });
      }
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
      this.loading.set(false);
    }
  }

  protected clear(): void {
    this.controller?.abort();
    this.controller = null;
    this.loading.set(false);
    this.projectName.set('');
    this.sourceCode.set('');
    this.language.set('auto');
    this.protheusVersion.set('');
    this.projectNameTouched.set(false);
    this.submitted.set(false);
    this.fieldErrors.set({});
    this.status.set(null);
    this.pasteResult.set(null);
  }

  protected updateLanguage(value: AnalysisLanguage): void {
    this.language.set(value);
    if (value !== 'advpl') {
      this.protheusVersion.set('');
    }
  }

  protected updateProtheusVersion(value: string): void {
    this.protheusVersion.set(value);
  }

  protected openLogin(): void {
    if (this.login.open() === false) {
      const notice = this.login.notice();
      if (notice !== '') {
        this.status.set({ tone: 'warning', message: notice });
      }
    }
  }

  protected handleDecided(): void {
    this.status.set({ tone: 'success', message: 'Decisão registrada para a correção.' });
  }

  protected openDetail(id: string): void {
    void this.router.navigate(['/history', id]);
  }

  protected handleRepositoryResult(analysis: Analysis): void {
    this.repositoryResult.set(analysis);
  }

  protected clearRepositoryResult(): void {
    this.repositoryResult.set(null);
  }

  private isVisible(
    submitted: boolean,
    touched: boolean,
    serverError: string | undefined,
  ): boolean {
    return submitted || touched || serverError !== undefined;
  }

  private focusFirstInvalid(): void {
    setTimeout(() => {
      this.host.nativeElement.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }, 0);
  }
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}
