import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';

import { ApiClient, isAbortError } from '../api/api-client';
import { isApiError } from '../api/api-error.mapper';
import { Analysis } from '../api/api.types';
import { AuthService } from '../auth/auth.service';
import { LoginPromptService } from '../auth/login-prompt.service';

export type HistoryState = 'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'unauthorized';

const SESSION_EXPIRED_MESSAGE = 'Sua sessão expirou. Entre novamente para continuar.';

/**
 * Owner-scoped history loaded on demand.
 *
 * There is deliberately no timer or effect that polls `GET /analyses`: the
 * endpoint is only requested when a signed-in user opens the overview/history
 * or presses "Atualizar". A visitor never triggers the request at all — the
 * authenticated endpoint is not called without a token.
 */
@Injectable({ providedIn: 'root' })
export class HistoryStore {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly prompts = inject(LoginPromptService);
  private readonly destroyRef = inject(DestroyRef);

  readonly items = signal<readonly Analysis[]>([]);
  readonly state = signal<HistoryState>('idle');
  readonly error = signal<string | null>(null);
  readonly loadedAt = signal<number | null>(null);

  readonly sorted = computed(() => sortAnalyses(this.items()));
  readonly total = computed(() => this.items().length);
  readonly averageScore = computed(() => averageScoreOf(this.items()));
  readonly latest = computed<Analysis | null>(() => this.sorted()[0] ?? null);
  readonly recent = computed(() => this.sorted().slice(0, 5));

  readonly isLoading = computed(() => this.state() === 'loading');
  readonly isVisitor = computed(() => !this.auth.isAuthenticated());
  readonly hasItems = computed(() => this.items().length > 0);

  private controller: AbortController | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.controller?.abort());
  }

  async load(limit = 20): Promise<void> {
    // The endpoint is authenticated: asking without a token would only produce
    // a 401 and an unnecessary request. Show the login prompt instead.
    if (!this.auth.isAuthenticated()) {
      this.items.set([]);
      this.error.set(null);
      this.state.set('unauthorized');
      return;
    }

    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;

    this.state.set('loading');
    this.error.set(null);

    try {
      const items = await this.api.listAnalyses(limit, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      this.items.set(items);
      this.loadedAt.set(Date.now());
      this.state.set(items.length === 0 ? 'empty' : 'ready');
    } catch (error) {
      if (isAbortError(error) || controller.signal.aborted) {
        return;
      }

      const unauthorized = isApiError(error) && error.kind === 'unauthorized';
      if (unauthorized) {
        this.items.set([]);
        this.state.set('unauthorized');
        this.auth.expireSession();
        this.prompts.open({
          mode: 'login',
          message: SESSION_EXPIRED_MESSAGE,
        });
        return;
      }

      this.state.set('error');
      this.error.set(
        isApiError(error)
          ? error.message
          : 'Não foi possível carregar o histórico. Tente novamente.',
      );
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }

  reset(): void {
    this.controller?.abort();
    this.controller = null;
    this.items.set([]);
    this.state.set('idle');
    this.error.set(null);
    this.loadedAt.set(null);
  }
}

function timestampOf(analysis: Analysis): number {
  const value = Date.parse(analysis.created_at);
  return Number.isNaN(value) ? Number.NEGATIVE_INFINITY : value;
}

/** Newest first; malformed dates go last without breaking the order. */
export function sortAnalyses(items: readonly Analysis[]): readonly Analysis[] {
  return [...items].sort((left, right) => timestampOf(right) - timestampOf(left));
}

/** Mean of the finite scores, ignoring analyses without a score. */
export function averageScoreOf(items: readonly Analysis[]): number | null {
  const scores = items
    .map((item) => item.result?.score)
    .filter((score): score is number => typeof score === 'number' && Number.isFinite(score));

  if (scores.length === 0) {
    return null;
  }
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}
