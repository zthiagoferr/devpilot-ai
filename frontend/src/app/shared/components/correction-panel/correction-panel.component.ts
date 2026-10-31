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
import { LOGIN_UNAVAILABLE_MESSAGE } from '../../../core/auth/auth-errors';
import { AuthService } from '../../../core/auth/auth.service';
import {
  AnalysisIssue,
  Correction,
  CorrectionCreate,
  CorrectionMode,
  CorrectionStatus,
  PostValidation,
} from '../../../core/api/api.types';
import { BadgeComponent, BadgeTone } from '../badge/badge.component';
import { ButtonComponent } from '../button/button.component';
import { createFieldId } from '../field/field-id';
import { IconComponent } from '../icon/icon.component';
import { InlineStatusComponent, InlineStatusTone } from '../inline-status/inline-status.component';
import { SourceViewerComponent } from '../source-viewer/source-viewer.component';
import { DiffLine, parseUnifiedDiff } from './diff';
import {
  ADVPL_DISCLAIMER,
  causeLabel,
  issueLocation,
  severityLabel,
  severityTone,
} from '../issue-list/issue-presentation';
import { postValidationMessage } from '../../../shared/utils/pt-br-messages';
import { correctedFilename, diffFilename, downloadText } from './download';
import { toIssueRef } from './correction-issue-ref';

interface PanelStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

interface ValidationPresentation {
  readonly label: string;
  readonly tone: BadgeTone;
  readonly message: string;
  readonly targetResolved: boolean;
  readonly resolvedCount: number;
  readonly originalCount: number;
  readonly remaining: readonly AnalysisIssue[];
  readonly newIssues: readonly AnalysisIssue[];
  readonly warnings: readonly AnalysisIssue[];
}

const DECISION_LABELS: Readonly<Record<CorrectionStatus, string>> = {
  pending: 'Aguardando decisão',
  approved: 'Aprovada',
  rejected: 'Rejeitada',
};

const DECISION_TONES: Readonly<Record<CorrectionStatus, BadgeTone>> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
};

/**
 * Requests and presents one AI correction for a heuristic issue.
 *
 * The panel never applies the suggestion: it only copies, downloads, and
 * records an explicit approve/reject decision. The local post-validation is
 * labelled as heuristic, never as an official build.
 */
@Component({
  selector: 'app-correction-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BadgeComponent,
    ButtonComponent,
    IconComponent,
    InlineStatusComponent,
    SourceViewerComponent,
  ],
  templateUrl: './correction-panel.component.html',
  styleUrl: './correction-panel.component.css',
})
export class CorrectionPanelComponent {
  /** A single issue (default mode). Optional because full mode uses `issues`. */
  readonly issue = input<AnalysisIssue | null>(null);
  readonly source = input.required<string>();
  readonly language = input<string | null>(null);
  readonly file = input<string | null>(null);
  readonly analysisId = input<string | null>(null);
  readonly protheusVersion = input<string | null>(null);
  readonly authenticated = input(false);
  /** `single` preserves the historical one-issue contract. */
  readonly mode = input<CorrectionMode>('single');
  /** Targets of a full correction. Ignored in single mode. */
  readonly issues = input<readonly AnalysisIssue[]>([]);
  /**
   * Incremented by the parent to start a full correction. Kept as an input so
   * the issue-list header button can own the trigger and the loading state.
   */
  readonly requestToken = input(0);

  readonly loginRequested = output<void>();
  readonly decided = output<Correction>();
  /** Emits whenever a provider request starts/finishes. */
  readonly busyChange = output<boolean>();

  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly panelId = createFieldId('correction');

  protected readonly correction = signal<Correction | null>(null);
  protected readonly requesting = signal(false);
  protected readonly deciding = signal(false);
  protected readonly decisionInFlight = signal<'approved' | 'rejected' | null>(null);
  protected readonly status = signal<PanelStatus | null>(null);
  protected readonly copied = signal(false);

  protected readonly headingId = `${this.panelId}-heading`;
  protected readonly validationLabelId = `${this.panelId}-validation`;

  private lastIssue: AnalysisIssue | null = null;
  private lastIssues: readonly AnalysisIssue[] | null = null;
  private lastMode: CorrectionMode = 'single';
  private lastAnalysisId: string | null | undefined = undefined;
  private lastRequestToken = 0;
  /** Bumped on every identity change; late responses for the old issue are dropped. */
  private generation = 0;

  constructor() {
    // The list reuses this panel instance when the visible result changes (a
    // tab switch) or when the issue input is rebound. A correction belongs to
    // one issue/analysis pair (or to one full-mode issue set), so the previous
    // state must not survive an identity change.
    effect(() => {
      const issue = this.issue();
      const issues = this.issues();
      const mode = this.mode();
      const analysisId = this.analysisId();
      if (
        issue === this.lastIssue &&
        issues === this.lastIssues &&
        mode === this.lastMode &&
        analysisId === this.lastAnalysisId
      ) {
        return;
      }
      this.lastIssue = issue;
      this.lastIssues = issues;
      this.lastMode = mode;
      this.lastAnalysisId = analysisId;
      this.generation += 1;
      this.correction.set(null);
      this.status.set(null);
      this.copied.set(false);
      this.requesting.set(false);
      this.deciding.set(false);
      this.decisionInFlight.set(null);
      this.busyChange.emit(false);
    });

    // A full correction is started by the issue-list header. The token input
    // decouples the trigger from the panel state, so the button can own the
    // loading/disabled presentation without duplicating the request logic.
    effect(() => {
      const token = this.requestToken();
      if (token === this.lastRequestToken) {
        return;
      }
      this.lastRequestToken = token;
      if (this.mode() === 'full' && token > 0) {
        void this.request();
      }
    });
  }

  protected readonly isFull = computed(() => this.mode() === 'full');

  protected readonly includedCount = computed(() =>
    this.isFull() ? this.issues().length : this.issue() === null ? 0 : 1,
  );

  protected readonly heading = computed(() =>
    this.isFull()
      ? `Correção de ${this.includedCount()} ${
          this.includedCount() === 1 ? 'problema' : 'problemas'
        } com IA`
      : 'Correção com IA',
  );

  protected readonly canRequest = computed(
    () =>
      this.source().trim() !== '' &&
      this.includedCount() > 0 &&
      !this.requesting(),
  );

  protected readonly canDecide = computed(
    () => this.correction()?.status === 'pending' && this.authenticated() && !this.deciding(),
  );

  protected readonly isAdvpl = computed(() => {
    const issueLanguage = (this.issue()?.language ?? '').trim().toLowerCase();
    const language = (this.language() ?? '').trim().toLowerCase();
    const listedAdvpl = this.issues().some(
      (issue) => (issue.language ?? '').trim().toLowerCase() === 'advpl',
    );
    return issueLanguage === 'advpl' || language === 'advpl' || listedAdvpl;
  });

  protected readonly advplDisclaimer = ADVPL_DISCLAIMER;

  protected readonly diffLines = computed<readonly DiffLine[]>(() =>
    parseUnifiedDiff(this.correction()?.diff ?? ''),
  );

  protected readonly validation = computed<ValidationPresentation>(() => {
    const postValidation = this.correction()?.post_validation;
    return validationPresentation(postValidation);
  });

  protected decisionLabel(status: CorrectionStatus): string {
    return DECISION_LABELS[status];
  }

  protected decisionTone(status: CorrectionStatus): BadgeTone {
    return DECISION_TONES[status];
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

  protected findingLocation(issue: AnalysisIssue): string {
    return issueLocation(issue, this.file());
  }

  protected async request(): Promise<void> {
    if (this.requesting()) {
      return;
    }
    if (this.source().trim() === '') {
      this.status.set({
        tone: 'warning',
        message: 'Selecione um arquivo com conteúdo para pedir uma correção.',
      });
      return;
    }
    if (this.includedCount() === 0) {
      this.status.set({
        tone: 'warning',
        message: 'Nenhum problema foi selecionado para a correção.',
      });
      return;
    }

    this.requesting.set(true);
    this.busyChange.emit(true);
    this.copied.set(false);
    this.status.set({
      tone: 'loading',
      message: this.isFull()
        ? `Gerando correção única para ${this.includedCount()} problema(s) com IA…`
        : 'Gerando correção com IA…',
    });
    const generation = this.generation;

    try {
      const correction = await this.api.createCorrection(this.requestPayload());
      if (generation !== this.generation) {
        return;
      }
      this.correction.set(correction);
      this.status.set({
        tone: correction.post_validation.status === 'failed' ? 'warning' : 'success',
        message:
          'Correção gerada. Revise o código, as diferenças e a validação local antes de decidir.',
      });
    } catch (error) {
      if (isAbortError(error) || generation !== this.generation) {
        return;
      }
      this.status.set({
        tone:
          isApiError(error) && error.status !== null && error.status >= 500 ? 'error' : 'warning',
        message: correctionErrorMessage(error),
      });
    } finally {
      // A superseded request must not clear the busy state of the request that
      // replaced it (the parent would re-enable the button with one in flight).
      if (generation === this.generation) {
        this.requesting.set(false);
        this.busyChange.emit(false);
      }
    }
  }

  protected async copy(): Promise<void> {
    const correction = this.correction();
    if (correction === null) {
      return;
    }

    if (typeof navigator === 'undefined' || navigator.clipboard?.writeText === undefined) {
      this.status.set({
        tone: 'warning',
        message: 'Copiar não é suportado neste navegador. Baixe o código corrigido.',
      });
      return;
    }

    try {
      await navigator.clipboard.writeText(correction.corrected_code);
      this.copied.set(true);
      this.status.set({ tone: 'success', message: 'Código corrigido copiado.' });
    } catch {
      this.status.set({
        tone: 'error',
        message: 'Não foi possível copiar o código. Tente baixar o arquivo.',
      });
    }
  }

  protected exportCorrected(): void {
    const correction = this.correction();
    if (correction === null) {
      return;
    }
    const ok = downloadText(
      correction.corrected_code,
      correctedFilename(correction.file, correction.id),
    );
    this.status.set(
      ok
        ? { tone: 'success', message: 'Download do código corrigido iniciado.' }
        : { tone: 'error', message: 'Não foi possível iniciar o download neste navegador.' },
    );
  }

  protected exportDiff(): void {
    const correction = this.correction();
    if (correction === null) {
      return;
    }
    const ok = downloadText(
      correction.diff,
      diffFilename(correction.file, correction.id),
      'text/x-diff;charset=utf-8',
    );
    this.status.set(
      ok
        ? { tone: 'success', message: 'Download das diferenças iniciado.' }
        : { tone: 'error', message: 'Não foi possível iniciar o download neste navegador.' },
    );
  }

  protected async decide(status: 'approved' | 'rejected'): Promise<void> {
    const correction = this.correction();
    if (correction === null || this.deciding()) {
      return;
    }
    if (!this.authenticated()) {
      if (!this.auth.isAuthConfigured) {
        this.status.set({ tone: 'warning', message: LOGIN_UNAVAILABLE_MESSAGE });
        return;
      }
      this.status.set({
        tone: 'warning',
        message: 'Entre na sua conta para aprovar ou rejeitar esta correção.',
      });
      this.loginRequested.emit();
      return;
    }

    this.deciding.set(true);
    this.decisionInFlight.set(status);
    this.status.set({
      tone: 'loading',
      message: status === 'approved' ? 'Aprovando correção…' : 'Rejeitando correção…',
    });
    const generation = this.generation;

    try {
      const updated = await this.api.decideCorrection(correction.id, { status });
      if (generation !== this.generation) {
        return;
      }
      this.correction.set(updated);
      this.status.set({
        tone: 'success',
        message:
          updated.status === 'approved'
            ? 'Correção aprovada. Nenhum código foi alterado automaticamente.'
            : 'Correção rejeitada.',
      });
      this.decided.emit(updated);
    } catch (error) {
      if (isAbortError(error) || generation !== this.generation) {
        return;
      }
      if (isApiError(error) && error.status === 409) {
        this.status.set({
          tone: 'warning',
          message: 'Esta correção já foi decidida. Recarregue a análise para ver o status atual.',
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
      if (generation === this.generation) {
        this.deciding.set(false);
        this.decisionInFlight.set(null);
      }
    }
  }

  protected requestLogin(): void {
    if (!this.auth.isAuthConfigured) {
      this.status.set({ tone: 'warning', message: LOGIN_UNAVAILABLE_MESSAGE });
      return;
    }
    this.loginRequested.emit();
  }

  private requestPayload(): CorrectionCreate {
    const language = this.language();
    const file = this.file();
    const analysisId = this.analysisId();
    const protheusVersion = this.protheusVersion();
    const base = {
      ...(analysisId ? { analysis_id: analysisId } : {}),
      ...(file ? { file } : {}),
      ...(language ? { language } : {}),
      source_code: this.source(),
      ...(protheusVersion ? { protheus_version: protheusVersion } : {}),
    };

    if (this.isFull()) {
      return {
        ...base,
        mode: 'full',
        issues: this.issues().map(toIssueRef),
      };
    }

    const issue = this.issue();
    return {
      ...base,
      ...(issue === null ? {} : { issue: toIssueRef(issue) }),
    };
  }
}

function validationPresentation(
  postValidation: PostValidation | undefined,
): ValidationPresentation {
  const status = postValidation?.status ?? 'not_run';
  const resolved = postValidation?.issues_resolved ?? [];
  const remaining = postValidation?.issues_remaining ?? [];
  const newIssues = postValidation?.issues_new ?? [];
  const warnings = postValidation?.issues_warnings ?? [];
  const details = {
    targetResolved: postValidation?.target_resolved === true,
    resolvedCount: resolved.length,
    originalCount: resolved.length + remaining.length,
    remaining,
    newIssues,
    warnings,
  };

  switch (status) {
    case 'passed':
      return {
        label: 'Passou',
        tone: 'success',
        message: postValidationMessage('passed', postValidation?.summary),
        ...details,
      };
    case 'failed':
      return {
        label: 'Falhou',
        tone: 'warning',
        message: postValidationMessage('failed', postValidation?.summary),
        ...details,
      };
    default:
      return {
        label: 'Não executada',
        tone: 'neutral',
        message: postValidationMessage('not_run', postValidation?.summary),
        ...details,
      };
  }
}

function correctionErrorMessage(error: unknown): string {
  if (!isApiError(error)) {
    return 'Não foi possível gerar a correção. Tente novamente.';
  }

  switch (error.status) {
    case 503:
      return 'A correção de IA não está configurada no servidor. Configure o provedor de LLM e tente novamente.';
    case 504:
      return 'A IA demorou para responder. Tente novamente ou use um arquivo menor.';
    case 502:
      return 'A IA retornou uma correção inválida. Tente novamente em instantes.';
    case 429:
      return error.retryAfterSeconds !== null && error.retryAfterSeconds > 0
        ? `Muitas solicitações de correção. Aguarde ${error.retryAfterSeconds} s e tente novamente.`
        : 'Muitas solicitações de correção. Aguarde alguns instantes e tente novamente.';
    case 413:
      return 'O código enviado é grande demais para correção. Reduza o arquivo e tente novamente.';
    case 401:
    case 403:
      return 'Sua sessão não permite solicitar esta correção. Entre novamente para continuar.';
    case 422:
      if (error.message.toLowerCase().includes('safety checks')) {
        return 'A correção proposta foi rejeitada pelas verificações de segurança.';
      }
      if (error.message.toLowerCase().includes('too many issues')) {
        return 'Há problemas demais para corrigir de uma vez. Reduza a quantidade e tente novamente.';
      }
      if (error.message.toLowerCase().includes('no issues to correct')) {
        return 'Nenhum problema foi encontrado para corrigir neste arquivo.';
      }
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
