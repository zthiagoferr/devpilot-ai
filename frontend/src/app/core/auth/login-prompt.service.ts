import { Injectable, signal } from '@angular/core';

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
 * Screens that require a session call `open()`; F5 fills the modal with the
 * Firebase forms while keeping this entry point unchanged.
 */
@Injectable({ providedIn: 'root' })
export class LoginPromptService {
  private readonly state = signal(false);
  private readonly modeState = signal<AuthMode>('login');
  private readonly messageState = signal('');

  readonly isOpen = this.state.asReadonly();
  readonly mode = this.modeState.asReadonly();
  readonly message = this.messageState.asReadonly();

  open(options: LoginPromptOptions = {}): void {
    this.modeState.set(options.mode ?? 'login');
    this.messageState.set(options.message ?? '');
    this.state.set(true);
  }

  close(): void {
    this.state.set(false);
  }
}
