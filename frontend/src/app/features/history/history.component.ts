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
import { resolveScoreStatus } from '../../shared/utils/pt-br-messages';

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
  selector: 'app-history',
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
  templateUrl: './history.component.html',
  styleUrl: './history.component.css',
})
export class HistoryComponent {
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

  constructor() {
    // Load on demand only; no interval/effect polls the history endpoint.
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

  protected refresh(): void {
    void this.history.load();
  }

  protected startAnalysis(): void {
    void this.router.navigate(['/analysis/new']);
  }

  protected originLabel(analysis: Analysis): string {
    return analysis.repository_url ? 'Repositório' : 'Manual';
  }

  protected statusLabel(analysis: Analysis): string {
    return STATUS_LABELS[analysis.status ?? '']?.label ?? 'Concluída';
  }

  protected statusTone(analysis: Analysis): BadgeTone {
    return STATUS_LABELS[analysis.status ?? '']?.tone ?? 'neutral';
  }

  protected scoreLabel(analysis: Analysis): string {
    const status = resolveScoreStatus(
      analysis.result?.score_status,
      analysis.result?.validation_skipped,
    );
    if (status === 'skipped' || status === 'unavailable') {
      return '—';
    }
    const score = analysis.result?.score;
    return typeof score === 'number' && Number.isFinite(score) ? `${Math.round(score)}/100` : '—';
  }

  protected formatDate(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
  }
}
