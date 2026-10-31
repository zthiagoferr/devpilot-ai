import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';

import { ApiClient, isAbortError } from '../../../core/api/api-client';
import { isApiError } from '../../../core/api/api-error.mapper';
import {
  AnalysisIssue,
  Correction,
  CorrectionBatchItem,
  CorrectionBatchResponse,
  CorrectionCreate,
  CorrectionRepositoryContext,
} from '../../../core/api/api.types';
import { BadgeComponent, BadgeTone } from '../badge/badge.component';
import { ButtonComponent } from '../button/button.component';
import { IconComponent } from '../icon/icon.component';
import { InlineStatusComponent, InlineStatusTone } from '../inline-status/inline-status.component';
import {
  ADVPL_DISCLAIMER,
  causeLabel,
  issueLocation,
  severityLabel,
  severityTone,
} from '../issue-list/issue-presentation';
import { DiffLine, parseUnifiedDiff } from '../correction-panel/diff';
import { toIssueRef } from '../correction-panel/correction-issue-ref';
import { postValidationMessage } from '../../utils/pt-br-messages';

/** Source material kept by the parent so a failed file can be retried alone. */
export interface CorrectionBatchSource {
  readonly source_code: string;
  readonly issues?: readonly AnalysisIssue[];
}

interface PanelStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

interface ValidationPresentation {
  readonly label: string;
  readonly tone: BadgeTone;
  readonly message: string;
  readonly resolvedCount: number;
  readonly originalCount: number;
  readonly remaining: readonly AnalysisIssue[];
  readonly newIssues: readonly AnalysisIssue[];
  readonly warnings: readonly AnalysisIssue[];
}

const STATUS_LABELS: Readonly<Record<CorrectionBatchItem['status'], string>> = {
  completed: 'Concluído',
  failed: 'Falhado',
  skipped: 'Pulado',
};

const STATUS_TONES: Readonly<Record<CorrectionBatchItem['status'], BadgeTone>> = {
  completed: 'success',
  failed: 'danger',
  skipped: 'warning',
};

const REASON_LABELS: Readonly<Record<string, string>> = {
  budget: 'orçamento de tempo esgotado',
  budget_exceeded: 'orçamento de tempo esgotado',
  no_issues: 'sem problemas detectados',
  sensitive_file: 'arquivo sensível não enviado',
  not_utf8: 'arquivo não está em UTF-8 válido',
  source_too_large: 'arquivo grande demais para correção',
  unsupported_language: 'linguagem não suportada',
  too_many_issues: 'problemas demais para corrigir de uma vez',
  timeout: 'tempo esgotado na IA',
  invalid_response: 'resposta inválida da IA',
  safety_rejected: 'correção rejeitada pelas verificações de segurança',
  provider_error: 'falha do provedor de IA',
  internal_error: 'erro interno ao corrigir o arquivo',
};

/**
 * Review panel for a batch correction.
 *
 * Every completed file is an independent persisted correction: approving one
 * never approves the others, and a failed file can be retried alone through the
 * existing single-file `full` correction flow. The panel never applies code.
 */
@Component({
  selector: 'app-correction-batch-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BadgeComponent, ButtonComponent, IconComponent, InlineStatusComponent],
  templateUrl: './correction-batch-panel.component.html',
  styleUrl: './correction-batch-panel.component.css',
})
export class CorrectionBatchPanelComponent {
  readonly batch = input.required<CorrectionBatchResponse>();
  /** Source of every loaded file, keyed by repository path (retry support). */
  readonly sources = input<Readonly<Record<string, CorrectionBatchSource>>>({});
  readonly language = input<string | null>(null);
  readonly analysisId = input<string | null>(null);
  readonly protheusVersion = input<string | null>(null);
  readonly repositoryContext = input<CorrectionRepositoryContext | null>(null);
  readonly authenticated = input(false);

  readonly loginRequested = output<void>();
  readonly decided = output<Correction>();
  readonly retried = output<CorrectionBatchItem>();

  private readonly api = inject(ApiClient);

  protected readonly items = signal<readonly CorrectionBatchItem[]>([]);
  protected readonly status = signal<PanelStatus | null>(null);
  protected readonly itemMessages = signal<Readonly<Record<string, PanelStatus>>>({});
  protected readonly busyPath = signal<string | null>(null);
  protected readonly decidingId = signal<string | null>(null);
  protected readonly decisionKind = signal<'approved' | 'rejected' | null>(null);

  private lastBatch: CorrectionBatchResponse | null = null;

  constructor() {
    // A new batch replaces the local view entirely: a stale retry/decision
    // message must never be attached to a different result.
    effect(() => {
      const batch = this.batch();
      if (batch === this.lastBatch) {
        return;
      }
      this.lastBatch = batch;
      this.items.set(batch.results);
      this.status.set(null);
      this.itemMessages.set({});
      this.busyPath.set(null);
      this.decidingId.set(null);
      this.decisionKind.set(null);
    });
  }

  protected readonly summary = computed(() => {
    const items = this.items();
    const completed = items.filter((item) => item.status === 'completed').length;
    const failed = items.filter((item) => item.status === 'failed').length;
    const skipped = items.filter((item) => item.status === 'skipped').length;
    const total = items.length;
    const resolved = items.reduce(
      (sum, item) => sum + (item.correction?.post_validation.issues_resolved?.length ?? 0),
      0,
    );
    const remaining = items.reduce(
      (sum, item) => sum + (item.correction?.post_validation.issues_remaining?.length ?? 0),
      0,
    );
    const introduced = items.reduce(
      (sum, item) => sum + (item.correction?.post_validation.issues_new?.length ?? 0),
      0,
    );

    return {
      total,
      completed,
      failed,
      skipped,
      resolved,
      remaining,
      introduced,
      text: [
        `${completed} de ${total} ${total === 1 ? 'arquivo' : 'arquivos'} ${
          completed === 1 ? 'concluído' : 'concluídos'
        }`,
        `${failed} ${failed === 1 ? 'falha' : 'falhas'}`,
        `${skipped} ${skipped === 1 ? 'pulado' : 'pulados'}`,
        `${resolved} ${resolved === 1 ? 'resolvido' : 'resolvidos'}`,
        `${remaining} ${remaining === 1 ? 'pendente' : 'pendentes'}`,
        `${introduced} ${introduced === 1 ? 'novo' : 'novos'}`,
      ].join(' · '),
    };
  });

  protected readonly hasPartial = computed(
    () => this.summary().failed > 0 || this.summary().skipped > 0,
  );

  protected readonly budgetExceeded = computed(
    () =>
      this.batch().budget_exceeded ||
      this.items().some((item) => item.reason === 'budget' || item.reason === 'budget_exceeded'),
  );

  protected readonly isAdvpl = computed(
    () => (this.language() ?? '').trim().toLowerCase() === 'advpl',
  );

  protected readonly advplDisclaimer = ADVPL_DISCLAIMER;

  protected statusLabel(status: CorrectionBatchItem['status']): string {
    return STATUS_LABELS[status];
  }

  protected statusTone(status: CorrectionBatchItem['status']): BadgeTone {
    return STATUS_TONES[status];
  }

  protected reasonLabel(item: CorrectionBatchItem): string {
    const reason = (item.reason ?? item.error_code ?? '').trim().toLowerCase();
    if (reason === '') {
      return item.status === 'failed' ? 'não foi possível corrigir este arquivo' : 'arquivo pulado';
    }
    return REASON_LABELS[reason] ?? reason;
  }

  protected messageFor(path: string): PanelStatus | null {
    return this.itemMessages()[path] ?? null;
  }

  protected issueCountLabel(item: CorrectionBatchItem): string {
    const count = item.issues_targeted;
    return `${count} ${count === 1 ? 'problema alvo' : 'problemas alvos'}`;
  }

  protected diffLines(item: CorrectionBatchItem): readonly DiffLine[] {
    return parseUnifiedDiff(item.correction?.diff ?? '');
  }

  protected validation(item: CorrectionBatchItem): ValidationPresentation {
    const postValidation = item.correction?.post_validation;
    const resolved = postValidation?.issues_resolved ?? [];
    const remaining = postValidation?.issues_remaining ?? [];
    const status = postValidation?.status ?? 'not_run';

    return {
      label: status === 'passed' ? 'Passou' : status === 'failed' ? 'Falhou' : 'Não executada',
      tone: status === 'passed' ? 'success' : status === 'failed' ? 'warning' : 'neutral',
      message: postValidationMessage(status, postValidation?.summary),
      resolvedCount: resolved.length,
      originalCount: resolved.length + remaining.length,
      remaining,
      newIssues: postValidation?.issues_new ?? [],
      warnings: postValidation?.issues_warnings ?? [],
    };
  }

  protected findingLabel(issue: AnalysisIssue): string {
    return causeLabel(issue) || issue.message;
  }

  protected findingSeverity(issue: AnalysisIssue): string {
    return severityLabel(issue);
  }

  protected findingTone(issue: AnalysisIssue): BadgeTone {
    return severityTone(issue);
  }

  protected findingLocation(issue: AnalysisIssue, path: string): string {
    return issueLocation(issue, path);
  }

  protected decisionInFlight(item: CorrectionBatchItem, kind?: 'approved' | 'rejected'): boolean {
    if (item.correction === undefined || item.correction === null) {
      return false;
    }
    if (this.decidingId() !== item.correction.id) {
      return false;
    }
    return kind === undefined || this.decisionKind() === kind;
  }

  protected canRetry(item: CorrectionBatchItem): boolean {
    return (
      item.status === 'failed' &&
      this.busyPath() === null &&
      this.sources()[item.path]?.source_code.trim() !== ''
    );
  }

  protected async retry(item: CorrectionBatchItem): Promise<void> {
    if (item.status !== 'failed' || this.busyPath() !== null) {
      return;
    }
    const source = this.sources()[item.path];
    if (source === undefined || source.source_code.trim() === '') {
      this.setItemMessage(item.path, {
        tone: 'warning',
        message: 'O conteúdo deste arquivo não está disponível. Carregue o repositório novamente.',
      });
      return;
    }

    this.busyPath.set(item.path);
    this.setItemMessage(item.path, {
      tone: 'loading',
      message: 'Corrigindo este arquivo novamente com IA…',
    });

    try {
      const updated = await this.api.createCorrection(this.retryPayload(item.path, source));
      const replacement: CorrectionBatchItem = {
        path: item.path,
        status: 'completed',
        correction: updated,
        issues_targeted: source.issues?.length ?? 0,
      };
      this.items.update((items) =>
        items.map((current) => (current.path === item.path ? replacement : current)),
      );
      this.setItemMessage(item.path, {
        tone: updated.post_validation.status === 'failed' ? 'warning' : 'success',
        message: 'Correção gerada novamente. Revise o resultado antes de decidir.',
      });
      this.retried.emit(replacement);
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
      this.setItemMessage(item.path, {
        tone:
          isApiError(error) && error.status !== null && error.status >= 500 ? 'error' : 'warning',
        message: retryErrorMessage(error),
      });
    } finally {
      if (this.busyPath() === item.path) {
        this.busyPath.set(null);
      }
    }
  }

  protected async decide(
    item: CorrectionBatchItem,
    status: 'approved' | 'rejected',
  ): Promise<void> {
    const correction = item.correction;
    if (correction === undefined || correction === null || this.decidingId() !== null) {
      return;
    }
    if (!this.authenticated()) {
      this.status.set({
        tone: 'warning',
        message: 'Entre na sua conta para aprovar ou rejeitar as correções.',
      });
      this.loginRequested.emit();
      return;
    }

    this.decidingId.set(correction.id);
    this.decisionKind.set(status);
    this.status.set({
      tone: 'loading',
      message: status === 'approved' ? 'Aprovando correção…' : 'Rejeitando correção…',
    });

    try {
      const updated = await this.api.decideCorrection(correction.id, { status });
      this.items.update((items) =>
        items.map((current) =>
          current.correction?.id === updated.id ? { ...current, correction: updated } : current,
        ),
      );
      this.status.set({
        tone: 'success',
        message:
          updated.status === 'approved'
            ? 'Correção aprovada. Nenhum código foi alterado automaticamente.'
            : 'Correção rejeitada.',
      });
      this.decided.emit(updated);
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
      if (isApiError(error) && error.status === 409) {
        this.status.set({
          tone: 'warning',
          message: 'Esta correção já foi decidida. Recarregue para ver o status atual.',
        });
      } else {
        if (isApiError(error) && (error.status === 401 || error.status === 403)) {
          this.loginRequested.emit();
        }
        this.status.set({
          tone: 'error',
          message: decisionErrorMessage(error),
        });
      }
    } finally {
      if (this.decidingId() === correction.id) {
        this.decidingId.set(null);
        this.decisionKind.set(null);
      }
    }
  }

  private retryPayload(path: string, source: CorrectionBatchSource): CorrectionCreate {
    const analysisId = this.analysisId();
    const language = this.language();
    const protheusVersion = this.protheusVersion();
    const context = this.repositoryContext();
    return {
      ...(analysisId ? { analysis_id: analysisId } : {}),
      file: path,
      ...(language ? { language } : {}),
      source_code: source.source_code,
      mode: 'full',
      issues: (source.issues ?? []).map(toIssueRef),
      ...(protheusVersion ? { protheus_version: protheusVersion } : {}),
      ...(context === null ? {} : { repository_context: context }),
    };
  }

  private setItemMessage(path: string, message: PanelStatus | null): void {
    this.itemMessages.update((current) => {
      if (message === null) {
        const { [path]: _removed, ...rest } = current;
        return rest;
      }
      return { ...current, [path]: message };
    });
  }
}

function retryErrorMessage(error: unknown): string {
  if (!isApiError(error)) {
    return 'Não foi possível corrigir este arquivo novamente. Tente outra vez.';
  }
  switch (error.status) {
    case 503:
      return 'A correção de IA não está configurada no servidor. Configure o provedor de LLM.';
    case 504:
      return 'A IA demorou para responder. Tente novamente ou use um arquivo menor.';
    case 502:
      return 'A IA retornou uma correção inválida. Tente novamente em instantes.';
    case 429:
      return error.retryAfterSeconds !== null && error.retryAfterSeconds > 0
        ? `Muitas solicitações. Aguarde ${error.retryAfterSeconds} s e tente novamente.`
        : 'Muitas solicitações. Aguarde alguns instantes e tente novamente.';
    case 413:
      return 'O arquivo é grande demais para correção.';
    case 401:
    case 403:
      return 'Sua sessão não permite solicitar esta correção. Entre novamente para continuar.';
    case 422:
      return 'A solicitação de correção é inválida. Revise o arquivo e tente novamente.';
    default:
      return error.message;
  }
}

function decisionErrorMessage(error: unknown): string {
  if (!isApiError(error)) {
    return 'Não foi possível registrar a decisão. Tente novamente.';
  }
  if (error.status === 401 || error.status === 403) {
    return 'Entre na sua conta para aprovar ou rejeitar esta correção.';
  }
  if (error.status === 404) {
    return 'Esta correção não foi encontrada. Ela pode ter sido removida.';
  }
  return error.message;
}
