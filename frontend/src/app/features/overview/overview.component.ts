import { ChangeDetectionStrategy, Component, computed, effect, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { Analysis } from '../../core/api/api.types';
import { AuthService } from '../../core/auth/auth.service';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { HistoryStore } from '../../core/history/history-store';
import { BadgeComponent, BadgeTone } from '../../shared/components/badge/badge.component';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { CardComponent } from '../../shared/components/card/card.component';
import { EmptyStateComponent } from '../../shared/components/empty-state/empty-state.component';
import { ErrorStateComponent } from '../../shared/components/error-state/error-state.component';
import { IconComponent } from '../../shared/components/icon/icon.component';
import { SkeletonComponent } from '../../shared/components/skeleton/skeleton.component';

interface Metric {
  readonly label: string;
  readonly value: string;
  readonly hint: string;
}

const DATE_FORMATTER = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short',
  timeStyle: 'short',
});

const STATUS_LABELS: Readonly<Record<string, { label: string; tone: BadgeTone }>> = {
  completed: { label: 'Concluída', tone: 'success' },
  failed: { label: 'Falhou', tone: 'danger' },
  running: { label: 'Em execução', tone: 'info' },
  pending: { label: 'Pendente', tone: 'warning' },
};

@Component({
  selector: 'app-overview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    IconComponent,
    SkeletonComponent,
  ],
  templateUrl: './overview.component.html',
  styleUrl: './overview.component.css',
})
export class OverviewComponent {
  private readonly router = inject(Router);
  protected readonly auth = inject(AuthService);
  protected readonly prompts = inject(LoginPromptService);
  protected readonly history = inject(HistoryStore);

  protected readonly loading = computed(() => this.history.state() === 'loading');
  protected readonly isVisitor = computed(() => !this.auth.isAuthenticated());
  protected readonly hasItems = computed(
    () => this.history.state() === 'ready' && this.history.total() > 0,
  );
  protected readonly isEmpty = computed(
    () => this.auth.isAuthenticated() && this.history.state() === 'empty',
  );
  protected readonly hasError = computed(() => this.history.state() === 'error');

  protected readonly metrics = computed<readonly Metric[]>(() => {
    const signedIn = this.auth.isAuthenticated();
    const loaded = this.history.state() === 'ready' || this.history.state() === 'empty';
    const total = loaded ? String(this.history.total()) : '—';
    const average = this.history.averageScore();
    const latest = this.history.latest();

    return [
      {
        label: 'Análises salvas',
        value: signedIn ? total : '—',
        hint: signedIn ? 'No histórico da sua conta' : 'Disponível ao entrar',
      },
      {
        label: 'Score médio',
        value: signedIn && loaded && average !== null ? average.toFixed(1) : '—',
        hint: 'Média dos scores registrados',
      },
      {
        label: 'Última análise',
        value: signedIn && latest !== null ? this.formatDate(latest.created_at) : '—',
        hint: latest !== null ? latest.project_name : 'Nenhuma análise ainda',
      },
    ];
  });

  protected readonly steps = [
    {
      title: 'Envie o código',
      description: 'Cole o arquivo ou selecione um repositório público do GitHub.',
    },
    {
      title: 'Agentes analisam',
      description: 'Código, testes e documentação são avaliados em paralelo.',
    },
    {
      title: 'Receba o relatório',
      description: 'Score, problemas priorizados e um resumo com próximos passos.',
    },
  ];

  constructor() {
    // History is owner-scoped and load-on-demand: this effect never polls, and
    // a visitor never reaches `GET /analyses`.
    effect(() => {
      if (!this.auth.ready()) {
        return;
      }
      if (!this.auth.isAuthenticated()) {
        if (this.history.state() !== 'idle') {
          this.history.reset();
        }
        return;
      }
      if (this.history.state() === 'idle') {
        void this.history.load();
      }
    });
  }

  protected startAnalysis(): void {
    void this.router.navigate(['/analysis/new']);
  }

  protected openHistory(): void {
    void this.router.navigate(['/history']);
  }

  protected refresh(): void {
    void this.history.load();
  }

  protected openDetail(analysis: Analysis): void {
    void this.router.navigate(['/history', analysis.id]);
  }

  protected statusLabel(analysis: Analysis): string {
    return STATUS_LABELS[analysis.status ?? '']?.label ?? 'Concluída';
  }

  protected statusTone(analysis: Analysis): BadgeTone {
    return STATUS_LABELS[analysis.status ?? '']?.tone ?? 'neutral';
  }

  protected scoreLabel(analysis: Analysis): string {
    const score = analysis.result?.score;
    return typeof score === 'number' && Number.isFinite(score) ? `${Math.round(score)}` : '—';
  }

  protected originLabel(analysis: Analysis): string {
    return analysis.repository_url ? 'Repositório' : 'Manual';
  }

  protected formatDate(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
  }
}
