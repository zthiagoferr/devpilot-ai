import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';

import { ApiClient, isAbortError } from '../../core/api/api-client';
import { isApiError } from '../../core/api/api-error.mapper';
import { ConfigService } from '../../core/config/config.service';

type ServiceState = 'checking' | 'online' | 'degraded' | 'offline' | 'unconfigured';
type FailureKind = 'http-503' | 'unexpected-response' | 'connection' | 'timeout';

const POLL_INTERVAL_MS = 15_000;
const REQUEST_TIMEOUT_MS = 8_000;

const LABELS: Readonly<Record<ServiceState, string>> = {
  checking: 'Verificando API',
  online: 'API operacional',
  degraded: 'API com restrições',
  offline: 'API indisponível',
  unconfigured: 'API não configurada',
};

const FAILURE_LABELS: Readonly<Record<FailureKind, string>> = {
  'http-503': 'API indisponível (HTTP 503) — verifique o estado do serviço',
  'unexpected-response': 'Resposta inesperada da API — verifique o estado do serviço',
  connection: 'Falha de conexão/CORS com a API',
  timeout: 'Tempo esgotado ao contatar a API',
};

/**
 * Polls the orchestrator health endpoint every 15 s.
 *
 * Polling pauses while the document is hidden (no background traffic), skips
 * when a request is already in flight and never triggers a history reload.
 */
@Component({
  selector: 'app-service-status',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="service" [attr.data-state]="state()">
      <span class="service__dot" aria-hidden="true"></span>
      <span class="service__label">{{ label() }}</span>
    </div>
    <span class="service__live" aria-live="polite" aria-atomic="true">{{ announcement() }}</span>
  `,
  styles: `
    :host {
      display: block;
    }

    .service {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      color: var(--color-muted);
      font-size: var(--text-caption);
    }

    .service__dot {
      width: 8px;
      height: 8px;
      flex: none;
      border-radius: 9999px;
      background-color: #a3a3a3;
      transition:
        background-color 150ms var(--ease-ui),
        box-shadow 150ms var(--ease-ui);
    }

    .service[data-state='online'] .service__dot {
      background-color: #fafafa;
      box-shadow: 0 0 0 3px rgb(250 250 250 / 0.14);
    }

    .service[data-state='degraded'] .service__dot {
      background-color: #a3a3a3;
      box-shadow: 0 0 0 3px rgb(163 163 163 / 0.12);
    }

    .service[data-state='offline'] .service__dot {
      background-color: transparent;
      box-shadow: inset 0 0 0 2px #fafafa;
    }

    .service[data-state='checking'] .service__dot {
      background-color: #a3a3a3;
      box-shadow: 0 0 0 3px rgb(163 163 163 / 0.12);
      animation: breathe 1.4s var(--ease-ui) infinite;
    }

    .service__live {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }

    @media (prefers-reduced-motion: reduce) {
      .service[data-state='checking'] .service__dot {
        animation: none;
      }
    }

    @keyframes breathe {
      50% {
        opacity: 0.35;
      }
    }
  `,
})
export class ServiceStatusComponent {
  private readonly api = inject(ApiClient);
  private readonly config = inject(ConfigService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly state = signal<ServiceState>('checking');
  private readonly failure = signal<FailureKind | null>(null);
  protected readonly label = computed(() => {
    const failure = this.failure();
    if (this.state() === 'offline' && failure !== null) {
      return FAILURE_LABELS[failure];
    }
    return LABELS[this.state()];
  });
  protected readonly announcement = signal('');

  private timer: ReturnType<typeof setInterval> | null = null;
  private controller: AbortController | null = null;
  private inFlight = false;
  private destroyed = false;

  constructor() {
    if (!this.config.hasApi()) {
      this.state.set('unconfigured');
      this.announcement.set('API não configurada para este ambiente.');
      return;
    }

    void this.check();
    this.timer = setInterval(() => {
      if (!document.hidden) {
        void this.check();
      }
    }, POLL_INTERVAL_MS);

    document.addEventListener('visibilitychange', this.handleVisibilityChange);

    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      if (this.timer !== null) {
        clearInterval(this.timer);
      }
      this.controller?.abort();
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    });
  }

  private readonly handleVisibilityChange = (): void => {
    if (!document.hidden) {
      void this.check();
    }
  };

  private async check(): Promise<void> {
    if (this.inFlight || this.destroyed || !this.config.hasApi()) {
      return;
    }

    this.inFlight = true;
    const controller = new AbortController();
    this.controller = controller;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
      const status = await this.api.getOrchestratorStatus(controller.signal);
      this.update(status.status === 'ready' ? 'online' : 'degraded');
    } catch (error) {
      if (!this.destroyed) {
        this.update('offline', classifyFailure(error, timedOut));
      }
    } finally {
      clearTimeout(timeout);
      if (this.controller === controller) {
        this.controller = null;
      }
      this.inFlight = false;
    }
  }

  private update(next: ServiceState, failure: FailureKind | null = null): void {
    if (this.state() === next && this.failure() === failure) {
      return;
    }
    this.state.set(next);
    this.failure.set(failure);
    this.announcement.set(
      next === 'offline' && failure !== null ? FAILURE_LABELS[failure] : LABELS[next],
    );
  }
}

function classifyFailure(error: unknown, timedOut: boolean): FailureKind {
  if (timedOut || isAbortError(error)) {
    return 'timeout';
  }
  if (!isApiError(error)) {
    return 'connection';
  }
  // An HTML/proxy body (for example a suspended Render service) is not an API
  // response at all; checking it before the status keeps the diagnosis clear.
  if (!error.bodyIsJson) {
    return 'unexpected-response';
  }
  if (error.kind === 'invalid-response') {
    return 'unexpected-response';
  }
  if (error.status === 503) {
    return 'http-503';
  }
  if (error.kind === 'network') {
    return 'connection';
  }
  return 'connection';
}
