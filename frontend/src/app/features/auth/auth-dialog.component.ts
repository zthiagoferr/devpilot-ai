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
import { findAuthProvider, type OAuthProviderId } from '../../core/auth/auth-providers';
import { AuthService } from '../../core/auth/auth.service';
import { AuthMode, needsEmailVerification } from '../../core/auth/auth.types';
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

type AuthAction =
  'password' | 'verification' | 'verify-check' | 'anonymous' | 'bootstrap' | OAuthProviderId;

const TITLES: Readonly<Record<AuthMode, string>> = {
  login: 'Entrar no DevPilot AI',
  register: 'Criar sua conta',
  reset: 'Recuperar senha',
};

const DESCRIPTIONS: Readonly<Record<AuthMode, string>> = {
  login: 'Use seu e-mail e senha ou continue com um provedor.',
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
  /** Single in-flight action; a second click is ignored while it runs. */
  protected readonly pendingAction = signal<AuthAction | null>(null);
  protected readonly status = signal<DialogStatus | null>(null);

  protected readonly busy = computed(() => this.pendingAction() !== null);
  protected readonly guestSession = computed(() => this.auth.isAnonymous());
  protected readonly title = computed(() =>
    this.guestSession() ? 'Você está como visitante' : TITLES[this.mode()],
  );
  protected readonly description = computed(() =>
    this.guestSession()
      ? 'Entre ou crie uma conta e preservaremos suas análises nesta sessão.'
      : DESCRIPTIONS[this.mode()],
  );
  protected readonly isReset = computed(() => this.mode() === 'reset');
  protected readonly emailAutocomplete = computed(() =>
    this.mode() === 'login' ? 'username' : 'email',
  );
  protected readonly available = computed(
    () => this.auth.configured && this.auth.status() !== 'error',
  );
  protected readonly showVerification = computed(() => needsEmailVerification(this.auth.user()));
  /** Countdown mirrored from the service's shared cooldown clock. */
  protected readonly resendSeconds = this.auth.resendRemainingSeconds;
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
      this.pendingAction.set(null);
      // Auth status/error are read untracked: an observer update must not reset
      // a form the user is already filling in.
      this.status.set(untracked(() => this.initialStatus(message || null)));
    });
  }

  protected selectMode(mode: AuthMode): void {
    this.mode.set(mode);
    this.password.set('');
    this.submitted.set(false);
    this.pendingAction.set(null);
    this.status.set(this.initialStatus(null));
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.busy()) {
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

    this.pendingAction.set('password');
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

    this.pendingAction.set(null);
    this.status.set({
      tone: result.ok ? (result.tone ?? 'success') : 'error',
      message: result.message,
    });

    if (result.ok && this.mode() === 'login') {
      this.prompts.close();
    }
  }

  protected async signInWithProvider(id: OAuthProviderId): Promise<void> {
    if (this.busy()) {
      return;
    }
    if (!this.available()) {
      this.status.set({ tone: 'warning', message: AUTH_UNAVAILABLE_MESSAGE });
      return;
    }

    const definition = findAuthProvider(id);
    if (definition === null) {
      return;
    }

    this.pendingAction.set(id);
    this.status.set({ tone: 'loading', message: `Abrindo ${definition.label}…` });
    const result = await this.auth.signInWithProvider(id);
    this.pendingAction.set(null);
    this.status.set({
      tone: result.ok ? (result.tone ?? 'success') : 'error',
      message: result.message,
    });
    if (result.ok && result.tone !== 'warning') {
      this.prompts.close();
    }
  }

  protected async resendVerification(): Promise<void> {
    if (this.busy()) {
      return;
    }
    this.pendingAction.set('verification');
    const result = await this.auth.resendVerificationEmail();
    this.pendingAction.set(null);
    this.status.set({
      tone: result.ok ? (result.tone ?? 'success') : 'error',
      message: result.message,
    });
  }

  /** "Já confirmei": forces a reload instead of polling the server. */
  protected async confirmVerification(): Promise<void> {
    if (this.busy()) {
      return;
    }
    this.pendingAction.set('verify-check');
    const result = await this.auth.refreshUser({ force: true, reason: 'manual' });
    this.pendingAction.set(null);

    if (!result.ok) {
      this.status.set({
        tone: 'error',
        message: result.message ?? 'Não foi possível verificar o e-mail agora. Tente novamente.',
      });
      return;
    }
    if (this.auth.emailVerified()) {
      this.status.set({ tone: 'success', message: 'E-mail confirmado. Obrigado!' });
      return;
    }
    this.status.set({
      tone: 'warning',
      message: 'Ainda não vemos a confirmação. Abra o link do e-mail e tente novamente.',
    });
  }

  /** Opt-in guest session; it is never started automatically on boot. */
  protected async continueAsGuest(): Promise<void> {
    if (this.busy()) {
      return;
    }
    if (!this.available()) {
      this.status.set({ tone: 'warning', message: AUTH_UNAVAILABLE_MESSAGE });
      return;
    }

    this.pendingAction.set('anonymous');
    this.status.set({ tone: 'loading', message: 'Iniciando sessão de visitante…' });
    const result = await this.auth.signInAnonymously();
    this.pendingAction.set(null);
    this.status.set({
      tone: result.ok ? (result.tone ?? 'success') : 'error',
      message: result.message,
    });
    if (result.ok) {
      this.prompts.close();
    }
  }

  protected async retryBootstrap(): Promise<void> {
    if (this.busy()) {
      return;
    }
    this.pendingAction.set('bootstrap');
    this.status.set({ tone: 'loading', message: 'Tentando reconectar…' });
    await this.auth.retryBootstrap();
    this.pendingAction.set(null);

    if (this.auth.status() === 'error') {
      this.status.set({
        tone: 'error',
        message: this.auth.error() ?? 'Ainda não foi possível iniciar a autenticação.',
      });
      return;
    }
    this.status.set(null);
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
