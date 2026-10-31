import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_PROVIDERS } from '../../core/auth/auth-providers';
import { AuthService } from '../../core/auth/auth.service';
import { AuthResult, AuthStatus, AuthUser } from '../../core/auth/auth.types';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { AuthDialogComponent } from './auth-dialog.component';

const GUEST_USER: AuthUser = {
  uid: 'guest-1',
  email: null,
  displayName: null,
  emailVerified: false,
  isAnonymous: true,
};

const UNVERIFIED_USER: AuthUser = {
  uid: 'user-1',
  email: 'dev@example.com',
  displayName: 'Dev',
  emailVerified: false,
  isAnonymous: false,
};

interface AuthStub {
  configured: boolean;
  isAuthConfigured: boolean;
  status: ReturnType<typeof signal<AuthStatus>>;
  loginAvailable: ReturnType<typeof computed<boolean>>;
  error: ReturnType<typeof signal<string | null>>;
  user: ReturnType<typeof signal<AuthUser | null>>;
  isAuthenticated: ReturnType<typeof computed<boolean>>;
  isAnonymous: ReturnType<typeof computed<boolean>>;
  email: ReturnType<typeof computed<string>>;
  emailVerified: ReturnType<typeof computed<boolean>>;
  providers: ReturnType<typeof computed<typeof AUTH_PROVIDERS>>;
  resendAvailableAt: ReturnType<typeof signal<number>>;
  resendRemainingSeconds: ReturnType<typeof computed<number>>;
  signIn: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
  sendPasswordReset: ReturnType<typeof vi.fn>;
  signInWithProvider: ReturnType<typeof vi.fn>;
  signInAnonymously: ReturnType<typeof vi.fn>;
  resendVerificationEmail: ReturnType<typeof vi.fn>;
  refreshUser: ReturnType<typeof vi.fn>;
  signOut: ReturnType<typeof vi.fn>;
  retryBootstrap: ReturnType<typeof vi.fn>;
}

describe('AuthDialogComponent', () => {
  let prompts: LoginPromptService;
  let stub: AuthStub;
  let fixture: ComponentFixture<AuthDialogComponent>;

  function createStub(configured = true): AuthStub {
    const user = signal<AuthUser | null>(null);
    const status = signal<AuthStatus>(configured ? 'ready' : 'unconfigured');
    const resendAvailableAt = signal(0);
    return {
      configured,
      isAuthConfigured: configured,
      status,
      loginAvailable: computed(() => configured && status() === 'ready'),
      error: signal<string | null>(null),
      user,
      isAuthenticated: computed(() => user() !== null),
      isAnonymous: computed(() => user()?.isAnonymous ?? false),
      email: computed(() => user()?.email ?? ''),
      emailVerified: computed(() => user()?.emailVerified ?? false),
      providers: computed(() => AUTH_PROVIDERS),
      resendAvailableAt,
      resendRemainingSeconds: computed(() => {
        const remaining = resendAvailableAt() - Date.now();
        return remaining > 0 ? Math.ceil(remaining / 1_000) : 0;
      }),
      signIn: vi.fn(async () => ({ ok: true, message: 'Sessão iniciada.' })),
      register: vi.fn(async () => ({ ok: true, message: 'Conta criada.' })),
      sendPasswordReset: vi.fn(async () => ({ ok: true, message: 'Link enviado.' })),
      signInWithProvider: vi.fn(async () => ({ ok: true, message: 'Sessão iniciada.' })),
      signInAnonymously: vi.fn(async () => ({ ok: true, message: 'Sessão de visitante.' })),
      resendVerificationEmail: vi.fn(async () => ({ ok: true, message: 'Reenviado.' })),
      refreshUser: vi.fn(async () => ({ ok: true })),
      signOut: vi.fn(async () => ({ ok: true, message: 'Você saiu.' })),
      retryBootstrap: vi.fn(async () => undefined),
    };
  }

  async function create(configured = true): Promise<void> {
    stub = createStub(configured);
    TestBed.configureTestingModule({
      imports: [AuthDialogComponent],
      providers: [{ provide: AuthService, useValue: stub }],
    });
    await TestBed.compileComponents();
    prompts = TestBed.inject(LoginPromptService);
    fixture = TestBed.createComponent(AuthDialogComponent);
  }

  function text(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function submitButton(): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
      'button[type="submit"]',
    ) as HTMLButtonElement;
  }

  function buttonByText(label: string): HTMLButtonElement | undefined {
    return Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button'),
    ).find((item) => (item.textContent ?? '').includes(label));
  }

  function clickByText(label: string): void {
    const button = buttonByText(label);
    expect(button, `botão "${label}"`).toBeDefined();
    button?.click();
  }

  function fill(selector: string, value: string): void {
    const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(selector);
    expect(input).not.toBeNull();
    if (input !== null) {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  beforeAll(() => {
    // jsdom does not implement the dialog top layer; the component only needs
    // `showModal`/`close` to mirror its open state during these unit tests.
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  });

  afterAll(() => {
    delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
    delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
  });

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('opens in login mode with credentials and the four provider buttons', async () => {
    await create();
    prompts.open();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(text()).toContain('Entrar no DevPilot AI');
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('input[type="email"]'),
    ).not.toBeNull();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('input[type="password"]'),
    ).not.toBeNull();
    expect(text()).toContain('Entrar com GitHub');
    expect(text()).toContain('Entrar com Google');
    expect(text()).toContain('Entrar com Apple');
    expect(text()).toContain('Entrar com Microsoft');
    expect(text()).toContain('ou');
  });

  it('switches between login, register and reset modes', async () => {
    await create();
    prompts.open();
    fixture.detectChanges();

    clickByText('Criar uma conta');
    fixture.detectChanges();
    expect(text()).toContain('Criar sua conta');
    expect(text()).toContain('Ao menos 6 caracteres');

    clickByText('Já tenho conta');
    fixture.detectChanges();
    expect(text()).toContain('Entrar no DevPilot AI');

    clickByText('Esqueci minha senha');
    fixture.detectChanges();
    expect(text()).toContain('Recuperar senha');
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('input[type="password"]'),
    ).toBeNull();
  });

  it('does not open the Firebase flow when authentication is not configured', async () => {
    await create(false);
    const opened = prompts.open();
    fixture.detectChanges();

    expect(opened).toBe(false);
    expect(prompts.isOpen()).toBe(false);
    expect(prompts.notice()).toContain('Login não disponível');
  });

  it('shows the contextual session message and submits the credentials', async () => {
    await create();
    prompts.open({ mode: 'login', message: 'Sua sessão expirou. Entre novamente.' });
    fixture.detectChanges();

    expect(text()).toContain('Sua sessão expirou');

    fill('input[type="email"]', 'dev@example.com');
    fill('input[type="password"]', 'secret123');
    fixture.detectChanges();

    submitButton().click();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(stub.signIn).toHaveBeenCalledWith('dev@example.com', 'secret123');
    expect(prompts.isOpen()).toBe(false);
  });

  it('validates the e-mail before calling the SDK', async () => {
    await create();
    prompts.open();
    fixture.detectChanges();

    fill('input[type="email"]', 'not-an-email');
    fill('input[type="password"]', 'secret123');
    fixture.detectChanges();
    submitButton().click();
    fixture.detectChanges();

    expect(text()).toContain('Informe um e-mail válido');
    expect(stub.signIn).not.toHaveBeenCalled();
  });

  it('shows loading only on the provider being used and disables the others', async () => {
    await create();
    let resolveProvider: ((result: AuthResult) => void) | undefined;
    stub.signInWithProvider.mockImplementation(
      () =>
        new Promise<AuthResult>((resolve) => {
          resolveProvider = resolve;
        }),
    );
    prompts.open();
    fixture.detectChanges();

    clickByText('Entrar com Google');
    fixture.detectChanges();

    expect(stub.signInWithProvider).toHaveBeenCalledWith('google');
    expect(buttonByText('Entrar com Google')?.getAttribute('aria-busy')).toBe('true');
    expect(buttonByText('Entrar com Apple')?.disabled).toBe(true);
    expect(buttonByText('Entrar com Microsoft')?.disabled).toBe(true);

    resolveProvider?.({ ok: true, message: 'Sessão iniciada com o Google.' });
    await Promise.resolve();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(buttonByText('Entrar com Google')?.getAttribute('aria-busy')).toBeNull();
    expect(prompts.isOpen()).toBe(false);
  });

  it('renders the provider error message in pt-BR', async () => {
    await create();
    stub.signInWithProvider.mockResolvedValue({
      ok: false,
      message: 'A entrada com Apple não está habilitada no projeto Firebase.',
    });
    prompts.open();
    fixture.detectChanges();

    clickByText('Entrar com Apple');
    await Promise.resolve();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(text()).toContain('A entrada com Apple não está habilitada no projeto Firebase.');
    expect(prompts.isOpen()).toBe(true);
  });

  it('opens in the error state and offers a retry action', async () => {
    await create();
    stub.status.set('error');
    stub.error.set('Não foi possível carregar o serviço de autenticação.');
    expect(prompts.open()).toBe(true);
    fixture.detectChanges();

    expect(text()).toContain('Não foi possível carregar o serviço de autenticação.');
    clickByText('Tentar novamente');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(stub.retryBootstrap).toHaveBeenCalledTimes(1);
  });

  it('exposes exactly six actions in login mode (submit, four providers, guest)', async () => {
    await create();
    prompts.open();
    fixture.detectChanges();

    const actionButtons = (fixture.nativeElement as HTMLElement).querySelectorAll(
      'app-button button',
    );

    expect(actionButtons).toHaveLength(6);
    expect(text()).toContain('Continuar como visitante');
  });

  it('starts a guest session only on demand and switches to the conversion copy', async () => {
    await create();
    prompts.open();
    fixture.detectChanges();

    clickByText('Continuar como visitante');
    await fixture.whenStable();
    fixture.detectChanges();

    expect(stub.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(prompts.isOpen()).toBe(false);

    // The next opening (already anonymous) advertises the conversion instead of
    // the visitor entry point and never shows the verification block.
    stub.user.set(GUEST_USER);
    prompts.open();
    fixture.detectChanges();

    expect(text()).toContain('Você está como visitante');
    expect(text()).toContain('preservaremos suas análises');
    expect(buttonByText('Continuar como visitante')).toBeUndefined();
    expect(text()).not.toContain('Reenviar confirmação');
  });

  it('shows the verification block only for an unconfirmed real account', async () => {
    await create();
    stub.user.set(UNVERIFIED_USER);
    prompts.open();
    fixture.detectChanges();

    expect(text()).toContain('Confirme seu e-mail');
    expect(text()).toContain('Reenviar confirmação');
    expect(text()).toContain('Já confirmei');
  });

  it('mirrors the shared cooldown countdown from the auth service', async () => {
    await create();
    stub.user.set(UNVERIFIED_USER);
    stub.resendAvailableAt.set(Date.now() + 5_000);
    prompts.open();
    fixture.detectChanges();

    expect(text()).toContain('Reenviar em 5s');
    expect(buttonByText('Reenviar em 5s')?.disabled).toBe(true);

    stub.resendAvailableAt.set(Date.now() + 3_000);
    fixture.detectChanges();
    expect(text()).toContain('Reenviar em 3s');
  });

  it('re-enables the resend action when the shared cooldown reaches zero', async () => {
    await create();
    stub.user.set(UNVERIFIED_USER);
    stub.resendAvailableAt.set(Date.now() + 2_000);
    prompts.open();
    fixture.detectChanges();

    expect(text()).toContain('Reenviar em 2s');

    stub.resendAvailableAt.set(0);
    fixture.detectChanges();

    expect(text()).toContain('Reenviar confirmação');
    expect(buttonByText('Reenviar confirmação')?.disabled).toBe(false);
  });

  it('forces a user refresh when the user says the e-mail was already confirmed', async () => {
    await create();
    stub.user.set(UNVERIFIED_USER);
    stub.refreshUser.mockResolvedValue({ ok: true });
    prompts.open();
    fixture.detectChanges();

    clickByText('Já confirmei');
    await fixture.whenStable();
    fixture.detectChanges();

    expect(stub.refreshUser).toHaveBeenCalledWith({ force: true, reason: 'manual' });
    expect(text()).toContain('Ainda não vemos a confirmação');
  });
});
