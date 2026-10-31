import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../../core/api/api-client';
import { AUTH_PROVIDERS } from '../../core/auth/auth-providers';
import { AuthService } from '../../core/auth/auth.service';
import { AuthStatus, AuthUser, initialsFor } from '../../core/auth/auth.types';
import { LoginPromptService } from '../../core/auth/login-prompt.service';
import { ConfigService } from '../../core/config/config.service';
import { AppShellComponent } from './app-shell.component';

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
  displayName: 'Dev Example',
  emailVerified: false,
  isAnonymous: false,
};

interface AuthStub {
  configured: boolean;
  isAuthConfigured: boolean;
  status: ReturnType<typeof signal<AuthStatus>>;
  user: ReturnType<typeof signal<AuthUser | null>>;
  isAuthenticated: ReturnType<typeof computed<boolean>>;
  isAnonymous: ReturnType<typeof computed<boolean>>;
  hasAccount: ReturnType<typeof computed<boolean>>;
  displayName: ReturnType<typeof computed<string>>;
  email: ReturnType<typeof computed<string>>;
  initials: ReturnType<typeof computed<string>>;
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

describe('AppShellComponent — account area', () => {
  let stub: AuthStub;
  let prompts: LoginPromptService;
  let fixture: ComponentFixture<AppShellComponent>;

  function createStub(): AuthStub {
    const user = signal<AuthUser | null>(null);
    const status = signal<AuthStatus>('ready');
    return {
      configured: true,
      isAuthConfigured: true,
      status,
      user,
      isAuthenticated: computed(() => user() !== null),
      isAnonymous: computed(() => user()?.isAnonymous ?? false),
      hasAccount: computed(() => user() !== null && !(user()?.isAnonymous ?? false)),
      displayName: computed(() => user()?.displayName ?? user()?.email ?? 'Visitante'),
      email: computed(() => user()?.email ?? ''),
      initials: computed(() => initialsFor(user())),
      emailVerified: computed(() => user()?.emailVerified ?? false),
      providers: computed(() => AUTH_PROVIDERS),
      resendAvailableAt: signal(0),
      resendRemainingSeconds: computed(() => 0),
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

  async function create(): Promise<void> {
    stub = createStub();
    TestBed.configureTestingModule({
      imports: [AppShellComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: stub },
        { provide: ApiClient, useValue: { getOrchestratorStatus: vi.fn() } },
        { provide: ConfigService, useValue: { hasApi: () => false } },
      ],
    });
    await TestBed.compileComponents();
    prompts = TestBed.inject(LoginPromptService);
    fixture = TestBed.createComponent(AppShellComponent);
    fixture.detectChanges();
    await fixture.whenStable();
  }

  function accountText(): string {
    const element = fixture.nativeElement as HTMLElement;
    return element.querySelector('section.account')?.textContent ?? '';
  }

  function accountButton(label: string): HTMLButtonElement | undefined {
    const element = fixture.nativeElement as HTMLElement;
    return Array.from(element.querySelectorAll<HTMLButtonElement>('section.account button')).find(
      (item) => (item.textContent ?? '').includes(label),
    );
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeAll(() => {
    // jsdom does not implement the dialog top layer.
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

  it('shows the account email and the verification banner only for an unconfirmed account', async () => {
    await create();
    stub.user.set(UNVERIFIED_USER);
    fixture.detectChanges();

    expect(accountText()).toContain('Dev Example');
    expect(accountText()).toContain('dev@example.com');
    expect(accountText()).toContain('Confirme seu e-mail');
    expect(accountButton('Criar conta')).toBeUndefined();

    stub.user.set({ ...UNVERIFIED_USER, emailVerified: true });
    fixture.detectChanges();

    expect(accountText()).not.toContain('Confirme seu e-mail');
  });

  it('labels a guest session and offers "Criar conta" plus "Sair"', async () => {
    await create();
    stub.user.set(GUEST_USER);
    fixture.detectChanges();

    expect(accountText()).toContain('Visitante');
    expect(accountText()).toContain('Sessão anônima');
    expect(accountText()).toContain('Anônimo');
    expect(accountButton('Criar conta')).toBeDefined();
    expect(accountButton('Sair')).toBeDefined();
    expect(accountText()).not.toContain('Confirme seu e-mail');
  });

  it('opens the dialog in register mode from the guest "Criar conta" action', async () => {
    await create();
    stub.user.set(GUEST_USER);
    fixture.detectChanges();

    accountButton('Criar conta')?.click();
    fixture.detectChanges();

    expect(prompts.isOpen()).toBe(true);
    expect(prompts.mode()).toBe('register');
  });

  it('refreshes the user on focus and on returning to the tab, and cleans up', async () => {
    const windowAdd = vi.spyOn(window, 'addEventListener');
    const windowRemove = vi.spyOn(window, 'removeEventListener');
    const documentAdd = vi.spyOn(document, 'addEventListener');
    const documentRemove = vi.spyOn(document, 'removeEventListener');

    await create();
    stub.user.set(UNVERIFIED_USER);
    fixture.detectChanges();

    const focusAdds = windowAdd.mock.calls.filter(([type]) => type === 'focus');
    expect(focusAdds).toHaveLength(1);
    const visibilityAdds = documentAdd.mock.calls.filter(([type]) => type === 'visibilitychange');
    expect(visibilityAdds).toHaveLength(1);

    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));

    expect(stub.refreshUser).toHaveBeenCalledWith({ reason: 'return' });
    expect(stub.refreshUser).toHaveBeenCalledTimes(2);

    const focusHandler = focusAdds[0]?.[1];
    fixture.destroy();

    expect(windowRemove).toHaveBeenCalledWith('focus', focusHandler);
    expect(documentRemove).toHaveBeenCalledWith('visibilitychange', visibilityAdds[0]?.[1]);
  });

  it('signs out from the guest session without touching the account identity', async () => {
    await create();
    stub.user.set(GUEST_USER);
    fixture.detectChanges();

    accountButton('Sair')?.click();
    await fixture.whenStable();

    expect(stub.signOut).toHaveBeenCalledTimes(1);
  });

  it('renders the raster brand mark in the single top dock brand chip', async () => {
    await create();
    const element = fixture.nativeElement as HTMLElement;
    const brandChips = Array.from(
      element.querySelectorAll<HTMLAnchorElement>('a.content__footer-chip--brand'),
    );

    expect(brandChips).toHaveLength(1);
    const chip = brandChips[0] as HTMLAnchorElement;
    const images = Array.from(chip.querySelectorAll<HTMLImageElement>('img'));
    expect(images).toHaveLength(1);
    expect(images[0]?.getAttribute('alt')).toBe('');
    expect(images[0]?.getAttribute('src')).toBe('brand/mark-128.png');
    expect(chip.textContent).toContain('DevPilot AI');

    expect(chip.querySelector('app-icon[name="sparkles"]')).toBeNull();
    expect(
      element.querySelectorAll('.content__footer-actions app-icon[name="sparkles"]'),
    ).toHaveLength(0);
  });
});
