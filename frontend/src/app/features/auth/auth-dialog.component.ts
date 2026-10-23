import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';

import { AUTH_UNAVAILABLE_MESSAGE } from '../../core/auth/auth-errors';
import { AuthService } from '../../core/auth/auth.service';
import { AuthMode } from '../../core/auth/auth.types';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { IconComponent } from '../../shared/components/icon/icon.component';
import {
  InlineStatusComponent,
  InlineStatusTone,
} from '../../shared/components/inline-status/inline-status.component';
import { InputComponent } from '../../shared/components/input/input.component';
import { ModalComponent } from '../../shared/components/modal/modal.component';

interface DialogStatus {
  readonly tone: InlineStatusTone;
  readonly message: string;
}

const TITLES: Readonly<Record<AuthMode, string>> = {
  login: 'Entrar no DevPilot AI',
  register: 'Criar sua conta',
  reset: 'Recuperar senha',
};

const DESCRIPTIONS: Readonly<Record<AuthMode, string>> = {
  login: 'Use seu e-mail e senha ou continue com o GitHub.',
  register: 'Crie uma conta para guardar o histórico das suas análises.',
  reset: 'Informe o e-mail da conta e enviaremos um link para redefinir a senha.',
};

/**
 * Firebase authentication dialog (login / register / reset).
 *
 * The same `<dialog>` component used by F1 supplies the top layer, focus trap,
 * Escape and focus return. This component only owns the form state, the mode
 * switch and the pt-BR feedback. When the deployment has no Firebase config,
 * every action is disabled and the degradation message is announced while the
 * visitor flows stay available.
 */
@Component({
  selector: 'app-auth-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, InlineStatusComponent, InputComponent, ModalComponent],
  templateUrl: './auth-dialog.component.html',
  styleUrl: './auth-dialog.component.css',
})
export class AuthDialogComponent {
  protected readonly prompts = inject(LoginPromptService);
  protected readonly auth = inject(AuthService);

  protected readonly mode = signal<AuthMode>('login');
  protected readonly email = signal('');
  protected readonly password = signal('');
  protected readonly submitted = signal(false);
  protected readonly submitting = signal(false);
  protected readonly status = signal<DialogStatus | null>(null);

  protected readonly title = computed(() => TITLES[this.mode()]);
  protected readonly description = computed(() => DESCRIPTIONS[this.mode()]);
  protected readonly isReset = computed(() => this.mode() === 'reset');
  protected readonly emailAutocomplete = computed(() =>
    this.mode() === 'login' ? 'username' : 'email',
  );
  protected readonly available = computed(
    () => this.auth.configured && this.auth.status() !== 'error',
  );
  protected readonly showVerification = computed(
    () => this.auth.isAuthenticated() && !this.auth.emailVerified(),
  );
  protected readonly submitLabel = computed(() => {
    switch (this.mode()) {
      case 'register':
        return 'Criar conta';
      case 'reset':
        return 'Enviar link';
      default:
        return 'Entrar';
    }
  });

  protected readonly emailError = computed(() => {
    if (!this.submitted()) {
      return '';
    }
    const value = this.email().trim();
    if (value === '') {
      return 'Informe seu e-mail.';
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      return 'Informe um e-mail válido.';
    }
    return '';
  });

  protected readonly passwordError = computed(() => {
    if (!this.submitted() || this.isReset()) {
      return '';
    }
    if (this.password() === '') {
      return 'Informe sua senha.';
    }
    if (this.mode() === 'register' && this.password().length < 6) {
      return 'A senha deve ter ao menos 6 caracteres.';
    }
    return '';
  });

  constructor() {
    effect(() => {
      if (!this.prompts.isOpen()) {
        return;
      }
      const requested = this.prompts.mode();
      const message = this.prompts.message();
      this.mode.set(requested);
      this.password.set('');
      this.submitted.set(false);
      this.submitting.set(false);
      // Auth status/error are read untracked: an observer update must not reset
      // a form the user is already filling in.
      this.status.set(untracked(() => this.initialStatus(message || null)));
    });
  }

  protected selectMode(mode: AuthMode): void {
    this.mode.set(mode);
    this.password.set('');
    this.submitted.set(false);
    this.status.set(this.initialStatus(null));
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.submitting()) {
      return;
    }

    this.submitted.set(true);
    if (this.emailError() !== '' || this.passwordError() !== '') {
      return;
    }

    if (!this.available()) {
      this.status.set({ tone: 'warning', message: AUTH_UNAVAILABLE_MESSAGE });
      return;
    }

    this.submitting.set(true);
    this.status.set({
      tone: 'loading',
      message: this.mode() === 'reset' ? 'Enviando o link…' : 'Conectando…',
    });

    const result =
      this.mode() === 'login'
        ? await this.auth.signIn(this.email(), this.password())
        : this.mode() === 'register'
          ? await this.auth.register(this.email(), this.password())
          : await this.auth.sendPasswordReset(this.email());

    this.submitting.set(false);
    this.status.set({ tone: result.ok ? 'success' : 'error', message: result.message });

    if (result.ok && this.mode() === 'login') {
      this.prompts.close();
    }
  }

  protected async signInWithGithub(): Promise<void> {
    if (this.submitting()) {
      return;
    }
    if (!this.available()) {
      this.status.set({ tone: 'warning', message: AUTH_UNAVAILABLE_MESSAGE });
      return;
    }

    this.submitting.set(true);
    this.status.set({ tone: 'loading', message: 'Abrindo o GitHub…' });
    const result = await this.auth.signInWithGithub();
    this.submitting.set(false);
    this.status.set({ tone: result.ok ? 'success' : 'error', message: result.message });
    if (result.ok) {
      this.prompts.close();
    }
  }

  protected async resendVerification(): Promise<void> {
    if (this.submitting()) {
      return;
    }
    this.submitting.set(true);
    const result = await this.auth.resendVerificationEmail();
    this.submitting.set(false);
    this.status.set({ tone: result.ok ? 'success' : 'error', message: result.message });
  }

  private initialStatus(message: string | null): DialogStatus | null {
    if (!this.auth.configured) {
      return { tone: 'warning', message: AUTH_UNAVAILABLE_MESSAGE };
    }
    if (this.auth.status() === 'error' && this.auth.error() !== null) {
      return { tone: 'error', message: this.auth.error() as string };
    }
    return message === null ? null : { tone: 'warning', message };
  }
}
