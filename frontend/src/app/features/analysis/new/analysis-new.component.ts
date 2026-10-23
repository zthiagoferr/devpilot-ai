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
import { isApiError } from '../../../core/api/api-error.mapper';
import { Analysis } from '../../../core/api/api.types';
import { BadgeComponent } from '../../../shared/components/badge/badge.component';
import { ButtonComponent } from '../../../shared/components/button/button.component';
import { CardComponent } from '../../../shared/components/card/card.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { IconComponent } from '../../../shared/components/icon/icon.component';
import {
  InlineStatusComponent,
  InlineStatusTone,
} from '../../../shared/components/inline-status/inline-status.component';
import { InputComponent } from '../../../shared/components/input/input.component';
import { ScoreRingComponent } from '../../../shared/components/score-ring/score-ring.component';
import { TabItem, TabsComponent } from '../../../shared/components/tabs/tabs.component';
import { TextareaComponent } from '../../../shared/components/textarea/textarea.component';

const MAX_SOURCE_BYTES = 1_000_000;

interface FormStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

const TABS: readonly TabItem[] = [
  { id: 'paste', label: 'Colar código' },
  { id: 'repository', label: 'Repositório' },
];

@Component({
  selector: 'app-analysis-new',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    EmptyStateComponent,
    IconComponent,
    InlineStatusComponent,
    InputComponent,
    ScoreRingComponent,
    TabsComponent,
    TextareaComponent,
  ],
  templateUrl: './analysis-new.component.html',
  styleUrl: './analysis-new.component.css',
})
export class AnalysisNewComponent {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  protected readonly tabs = TABS;
  protected readonly activeTab = signal('paste');

  protected readonly projectName = signal('');
  protected readonly sourceCode = signal('');
  protected readonly projectNameTouched = signal(false);
  protected readonly submitted = signal(false);
  protected readonly loading = signal(false);
  protected readonly fieldErrors = signal<Readonly<Record<string, string>>>({});
  protected readonly status = signal<FormStatus | null>(null);
  protected readonly result = signal<Analysis | null>(null);

  protected readonly sourceBytes = computed(() => byteLength(this.sourceCode()));

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
  protected readonly resultSummary = computed(() => {
    const summary = this.result()?.result?.summary?.trim();
    return summary === undefined || summary === '' ? null : summary;
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
    this.result.set(null);
    this.status.set({
      tone: 'loading',
      message: 'Analisando com os agentes. Isso pode levar alguns segundos.',
    });

    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;

    try {
      const analysis = await this.api.createAnalysis(
        {
          task: 'code_analysis',
          project_name: this.projectName().trim(),
          source_code: this.sourceCode(),
        },
        controller.signal,
      );

      this.result.set(analysis);
      this.status.set({
        tone: analysis.status === 'completed' ? 'success' : 'warning',
        message: this.successMessage(analysis),
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
    this.projectNameTouched.set(false);
    this.submitted.set(false);
    this.fieldErrors.set({});
    this.status.set(null);
    this.result.set(null);
  }

  protected openDetail(id: string): void {
    void this.router.navigate(['/history', id]);
  }

  private successMessage(analysis: Analysis): string {
    const score = analysis.result?.score;
    const issueCount = analysis.result?.issues?.length ?? 0;
    const parts = [analysis.status === 'completed' ? 'Análise concluída.' : 'Análise finalizada.'];

    if (typeof score === 'number' && Number.isFinite(score)) {
      parts.push(`Score ${score}/100.`);
    }
    parts.push(
      issueCount === 0
        ? 'Nenhum problema encontrado.'
        : `${issueCount} ${issueCount === 1 ? 'problema encontrado' : 'problemas encontrados'}.`,
    );
    return parts.join(' ');
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
