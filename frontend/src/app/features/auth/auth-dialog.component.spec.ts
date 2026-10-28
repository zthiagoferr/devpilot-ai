import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService } from '../../core/auth/auth.service';
import { AuthStatus, AuthUser } from '../../core/auth/auth.types';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { AuthDialogComponent } from './auth-dialog.component';

interface AuthStub {
  configured: boolean;
  isAuthConfigured: boolean;
  status: ReturnType<typeof signal<AuthStatus>>;
  loginAvailable: ReturnType<typeof computed<boolean>>;
  error: ReturnType<typeof signal<string | null>>;
  user: ReturnType<typeof signal<AuthUser | null>>;
  isAuthenticated: ReturnType<typeof computed<boolean>>;
  email: ReturnType<typeof computed<string>>;
  emailVerified: ReturnType<typeof computed<boolean>>;
  signIn: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
  sendPasswordReset: ReturnType<typeof vi.fn>;
  signInWithGithub: ReturnType<typeof vi.fn>;
  resendVerificationEmail: ReturnType<typeof vi.fn>;
  signOut: ReturnType<typeof vi.fn>;
}

describe('AuthDialogComponent', () => {
  let prompts: LoginPromptService;
  let stub: AuthStub;
  let fixture: ComponentFixture<AuthDialogComponent>;

  function createStub(configured = true): AuthStub {
    const user = signal<AuthUser | null>(null);
    const status = signal<AuthStatus>(configured ? 'ready' : 'unconfigured');
    return {
      configured,
      isAuthConfigured: configured,
      status,
      loginAvailable: computed(() => configured && status() === 'ready'),
      error: signal<string | null>(null),
      user,
      isAuthenticated: computed(() => user() !== null),
      email: computed(() => user()?.email ?? ''),
      emailVerified: computed(() => user()?.emailVerified ?? false),
      signIn: vi.fn(async () => ({ ok: true, message: 'Sessão iniciada.' })),
      register: vi.fn(async () => ({ ok: true, message: 'Conta criada.' })),
      sendPasswordReset: vi.fn(async () => ({ ok: true, message: 'Link enviado.' })),
      signInWithGithub: vi.fn(async () => ({ ok: true, message: 'Sessão iniciada.' })),
      resendVerificationEmail: vi.fn(async () => ({ ok: true, message: 'Reenviado.' })),
      signOut: vi.fn(async () => ({ ok: true, message: 'Você saiu.' })),
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

  function clickByText(label: string): void {
    const button = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('button'),
    ).find((item) => (item.textContent ?? '').includes(label));
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

  it('opens in login mode with an e-mail and a password field', async () => {
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
});
