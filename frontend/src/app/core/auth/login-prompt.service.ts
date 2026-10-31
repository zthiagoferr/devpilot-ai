import { Injectable, inject, signal } from '@angular/core';

import {
  LOGIN_AUTH_ERROR_MESSAGE,
  LOGIN_INITIALIZING_MESSAGE,
  LOGIN_UNAVAILABLE_MESSAGE,
} from './auth-errors';
import { AuthService } from './auth.service';
import { AuthMode } from './auth.types';

export interface LoginPromptOptions {
  /** Form shown first when the dialog opens. */
  readonly mode?: AuthMode;
  /** Contextual message (for example "Sua sessão expirou"). */
  readonly message?: string;
}

/**
 * Coordinates the authentication dialog.
 *
 * Screens that require a session call `open()`. The dialog is never opened
 * while the Firebase flow is unusable: the call returns `false` and `notice()`
 * exposes a pt-BR explanation. That covers both a deployment without public
 * Firebase configuration and a configured deployment whose SDK bootstrap
 * failed (invalid key, blocked network, provider disabled). While the SDK is
 * still loading the dialog stays closed with a transient notice instead of
 * showing a form that would fail on submit.
 */
@Injectable({ providedIn: 'root' })
export class LoginPromptService {
  private readonly auth = inject(AuthService);
  private readonly state = signal(false);
  private readonly modeState = signal<AuthMode>('login');
  private readonly messageState = signal('');
  private readonly noticeState = signal('');

  readonly isOpen = this.state.asReadonly();
  readonly mode = this.modeState.asReadonly();
  readonly message = this.messageState.asReadonly();
  readonly notice = this.noticeState.asReadonly();

  /** Open the dialog; returns `false` when authentication is unusable. */
  open(options: LoginPromptOptions = {}): boolean {
    if (!this.auth.isAuthConfigured) {
      this.noticeState.set(LOGIN_UNAVAILABLE_MESSAGE);
      return false;
    }

    // `error` is allowed on purpose: the dialog shows the failure and a
    // "Tentar novamente" action that calls `retryBootstrap()`. Only the
    // transient states (idle/loading) and unconfigured deployments stay closed.
    const status = this.auth.status();
    if (status !== 'ready' && status !== 'error') {
      this.noticeState.set(this.unavailableMessage());
      return false;
    }

    this.noticeState.set('');
    this.modeState.set(options.mode ?? 'login');
    this.messageState.set(options.message ?? '');
    this.state.set(true);
    return true;
  }

  close(): void {
    this.state.set(false);
  }

  clearNotice(): void {
    this.noticeState.set('');
  }

  private unavailableMessage(): string {
    return this.auth.status() === 'error' ? LOGIN_AUTH_ERROR_MESSAGE : LOGIN_INITIALIZING_MESSAGE;
  }
}
