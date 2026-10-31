import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiClient, isAbortError } from '../../../core/api/api-client';
import { ApiError, isApiError } from '../../../core/api/api-error.mapper';
import { Analysis, AnalysisIssue } from '../../../core/api/api.types';
import { AuthService } from '../../../core/auth/auth.service';
import { LoginPromptService } from '../../../core/auth/login-prompt.service';
import { BadgeComponent, BadgeTone } from '../../../shared/components/badge/badge.component';
import { ButtonComponent } from '../../../shared/components/button/button.component';
import { CardComponent } from '../../../shared/components/card/card.component';
import { CoverageSummaryComponent } from '../../../shared/components/coverage-summary/coverage-summary.component';
import { ErrorStateComponent } from '../../../shared/components/error-state/error-state.component';
import { IconComponent } from '../../../shared/components/icon/icon.component';
import { IssueListComponent } from '../../../shared/components/issue-list/issue-list.component';
import { languageLabel } from '../../../shared/components/language-select/language-options';
import { ScoreRingComponent } from '../../../shared/components/score-ring/score-ring.component';
import { SkeletonComponent } from '../../../shared/components/skeleton/skeleton.component';
import { SourceViewerComponent } from '../../../shared/components/source-viewer/source-viewer.component';
import {
  STRUCTURAL_SCORE_NOTE,
  analysisSummaryPtBr,
  resolveScoreStatus,
  scoreStatusEmptyLabel,
} from '../../../shared/utils/pt-br-messages';

type LoadState = 'loading' | 'ready' | 'unauthorized' | 'error';

interface BadgePresentation {
  readonly label: string;
  readonly tone: BadgeTone;
}

const DATE_FORMATTER = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

const STATUS_PRESENTATION: Readonly<Record<string, BadgePresentation>> = {
  completed: { label: 'Concluída', tone: 'success' },
  failed: { label: 'Falhou', tone: 'danger' },
  running: { label: 'Em execução', tone: 'info' },
  pending: { label: 'Pendente', tone: 'warning' },
};

const TASK_LABELS: Readonly<Record<string, string>> = {
  code_analysis: 'Análise completa',
  full_analysis: 'Análise completa',
  code: 'Análise de código',
  tests: 'Análise de testes',
  docs: 'Análise de documentação',
};

@Component({
  selector: 'app-analysis-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CoverageSummaryComponent,
    ErrorStateComponent,
    IconComponent,
    IssueListComponent,
    ScoreRingComponent,
    SkeletonComponent,
    SourceViewerComponent,
  ],
  templateUrl: './analysis-detail.component.html',
  styleUrl: './analysis-detail.component.css',
})
export class AnalysisDetailComponent {
  readonly id = input.required<string>();

  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly account = inject(AuthService);
  protected readonly auth = inject(LoginPromptService);

  protected readonly state = signal<LoadState>('loading');
  protected readonly error = signal<ApiError | null>(null);
  protected readonly analysis = signal<Analysis | null>(null);

  private readonly reloadToken = signal(0);

  constructor() {
    effect((onCleanup) => {
      const id = this.id();
      this.reloadToken();

      const controller = new AbortController();
      onCleanup(() => controller.abort());
      void this.load(id, controller.signal);
    });
  }

  protected readonly validationSkipped = computed(
    () => this.analysis()?.result?.validation_skipped === true,
  );

  protected readonly scoreStatus = computed(() =>
    resolveScoreStatus(
      this.analysis()?.result?.score_status,
      this.validationSkipped(),
    ),
  );

  protected readonly scoreEmptyLabel = computed(() => scoreStatusEmptyLabel(this.scoreStatus()));

  protected readonly coverage = computed(() => this.analysis()?.result?.coverage ?? null);

  protected readonly score = computed(() => {
    const status = this.scoreStatus();
    if (status === 'skipped' || status === 'unavailable') {
      return null;
    }
    return this.analysis()?.result?.score ?? null;
  });

  protected readonly structuralNote = computed(() =>
    this.scoreStatus() === 'evaluated' && this.issues().length === 0
      ? STRUCTURAL_SCORE_NOTE
      : null,
  );

  protected readonly summary = computed(() => {
    const analysis = this.analysis();
    if (this.scoreStatus() === 'skipped') {
      return 'Idioma não reconhecido — selecione manualmente. A análise estrutural não foi executada.';
    }
    const result = analysis?.result;
    return analysisSummaryPtBr({
      summary: result?.summary,
      score: this.score(),
      issueCount: result?.issues?.length ?? 0,
      status: analysis?.status,
    });
  });

  protected readonly issues = computed<readonly AnalysisIssue[]>(
    () => this.analysis()?.result?.issues ?? [],
  );

  protected readonly analyzedLanguage = computed(() => this.analysis()?.result?.language ?? null);

  protected readonly analyzedLanguageLabel = computed(() => {
    const language = this.analyzedLanguage();
    return language === null || language.trim() === '' ? null : languageLabel(language);
  });

  protected readonly confidenceLabel = computed(() => {
    const confidence = this.analysis()?.result?.confidence;
    return typeof confidence === 'number' && Number.isFinite(confidence)
      ? `${Math.round(confidence * 100)}% de confiança`
      : null;
  });

  protected readonly isAuthenticated = computed(() => this.account.isAuthenticated());

  protected readonly scoreHint = computed(() => {
    switch (this.scoreStatus()) {
      case 'skipped':
        return 'Idioma não reconhecido — selecione manualmente.';
      case 'unavailable':
        return 'Validação indisponível';
      case 'partial':
        return 'Análise parcial — confirme a linguagem manualmente.';
      default:
        break;
    }
    const value = this.score();
    if (value === null || !Number.isFinite(value)) {
      return 'Score não disponível';
    }
    if (value >= 80) {
      return 'Bom estado geral';
    }
    if (value >= 60) {
      return 'Atenção em pontos isolados';
    }
    return 'Revisão recomendada';
  });

  protected readonly status = computed<BadgePresentation>(
    () =>
      STATUS_PRESENTATION[this.analysis()?.status ?? ''] ?? {
        label: 'Desconhecido',
        tone: 'neutral',
      },
  );

  protected readonly taskLabel = computed(
    () => TASK_LABELS[this.analysis()?.task ?? ''] ?? this.analysis()?.task ?? 'Análise',
  );

  protected readonly originLabel = computed(() =>
    this.analysis()?.repository_url ? 'Repositório' : 'Manual',
  );

  protected readonly repositoryUrl = computed(() => this.analysis()?.repository_url ?? null);

  protected readonly createdAt = computed(() => {
    const value = this.analysis()?.created_at;
    if (value === undefined) {
      return '';
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
  });

  protected readonly errorTitle = computed(() => {
    const error = this.error();
    if (error === null) {
      return 'Não foi possível carregar a análise';
    }
    switch (error.kind) {
      case 'not-found':
        return 'Análise não encontrada';
      case 'rate-limited':
        return 'Muitas solicitações';
      case 'network':
        return 'Sem conexão com a API';
      case 'unavailable':
        return 'API não configurada';
      default:
        return 'Não foi possível carregar a análise';
    }
  });

  protected readonly errorDescription = computed(
    () => this.error()?.message ?? 'Tente novamente em instantes.',
  );

  protected readonly canRetry = computed(() => {
    const kind = this.error()?.kind;
    return kind !== 'not-found' && kind !== 'unauthorized' && kind !== 'unavailable';
  });

  protected retry(): void {
    this.reloadToken.update((value) => value + 1);
  }

  protected openLogin(): void {
    this.auth.open();
  }
  protected goToNewAnalysis(): void {
    void this.router.navigate(['/analysis/new']);
  }

  private async load(id: string, signal: AbortSignal): Promise<void> {
    this.state.set('loading');
    this.error.set(null);
    this.analysis.set(null);

    try {
      const analysis = await this.api.getAnalysis(id, signal);
      if (signal.aborted) {
        return;
      }
      this.analysis.set(analysis);
      this.state.set('ready');
    } catch (error) {
      if (isAbortError(error) || signal.aborted) {
        return;
      }
      if (isApiError(error)) {
        this.error.set(error);
        this.state.set(error.kind === 'unauthorized' ? 'unauthorized' : 'error');
        if (error.kind === 'unauthorized' && this.account.isAuthenticated()) {
          // The token was rejected: drop the local session and ask for a new
          // login instead of leaving the UI in a half-signed-in state.
          this.account.expireSession();
          this.auth.open({
            mode: 'login',
            message: 'Sua sessão expirou. Entre novamente para continuar.',
          });
        }
      } else {
        this.error.set(
          new ApiError('unknown', 'Falha inesperada ao carregar a análise. Tente novamente.'),
        );
        this.state.set('error');
      }
    }
  }
}
