import { createEnvironmentInjector, EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ConfigService } from '../config/config.service';
import { VERIFICATION_RESEND_COOLDOWN_MS, AuthService } from './auth.service';
import { needsEmailVerification } from './auth.types';
import { FIREBASE_AUTH_LOADER } from './firebase-auth-loader';
import {
  createFakeFirebaseAuth,
  createFakeUser,
  type FakeFirebaseAuth,
  type FakeOAuthProvider,
} from './testing/fake-firebase-auth';

describe('AuthService', () => {
  const defaultConfig = { apiKey: 'public-key', projectId: 'project' };

  function create(
    firebase: Record<string, unknown> = defaultConfig,
    extraConfig: Record<string, unknown> = {},
  ): {
    auth: AuthService;
    fake: FakeFirebaseAuth;
  } {
    const fake = createFakeFirebaseAuth();
    TestBed.configureTestingModule({
      providers: [
        AuthService,
        { provide: FIREBASE_AUTH_LOADER, useValue: fake.loader },
        { provide: ConfigService, useValue: { firebase, basePath: '', ...extraConfig } },
      ],
    });
    return { auth: TestBed.inject(AuthService), fake };
  }

  async function flush(times = 5): Promise<void> {
    for (let index = 0; index < times; index += 1) {
      await Promise.resolve();
    }
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('registers onIdTokenChanged and releases it when the injector is destroyed', async () => {
    const fake = createFakeFirebaseAuth();
    const injector = createEnvironmentInjector(
      [
        AuthService,
        { provide: FIREBASE_AUTH_LOADER, useValue: fake.loader },
        { provide: ConfigService, useValue: { firebase: defaultConfig } },
      ],
      TestBed.inject(EnvironmentInjector),
    );
    const auth = injector.get(AuthService);

    await auth.initialize();

    expect(fake.subscriptions).toBe(1);
    expect(fake.listeners).toHaveLength(1);

    injector.destroy();

    expect(fake.unsubscribes).toBe(1);
    expect(fake.listeners).toHaveLength(0);
  });

  it('marks the first emission as ready and projects the user (including isAnonymous)', async () => {
    const { auth, fake } = create();
    await auth.initialize();

    expect(auth.status()).toBe('loading');

    fake.emitUser(
      createFakeUser({
        uid: 'user-1',
        email: 'ana@example.com',
        displayName: 'Ana',
        emailVerified: true,
        isAnonymous: false,
      }),
    );

    expect(auth.status()).toBe('ready');
    expect(auth.ready()).toBe(true);
    expect(auth.user()).toEqual({
      uid: 'user-1',
      email: 'ana@example.com',
      displayName: 'Ana',
      emailVerified: true,
      isAnonymous: false,
    });
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.hasAccount()).toBe(true);
  });

  it('projects an anonymous visitor without treating it as an account', async () => {
    const { auth, fake } = create();
    await auth.initialize();

    fake.emitUser(createFakeUser({ isAnonymous: true, email: null, displayName: null }));

    expect(auth.isAnonymous()).toBe(true);
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.hasAccount()).toBe(false);
  });

  it('performs exactly one boot reload for an unverified user and propagates the result', async () => {
    const { auth, fake } = create();
    const user = createFakeUser({
      emailVerified: false,
      onReload: (current) => {
        current.emailVerified = true;
      },
    });
    await auth.initialize();

    fake.emitUser(user);
    await flush();

    expect(user.reloadCalls).toBe(1);
    expect(auth.emailVerified()).toBe(true);
    expect(auth.user()?.emailVerified).toBe(true);
    expect(auth.status()).toBe('ready');
  });

  it('does not schedule a boot reload for a guest session', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const guest = createFakeUser({
      isAnonymous: true,
      email: null,
      displayName: null,
      emailVerified: false,
    });

    fake.emitUser(guest);
    await flush();

    expect(guest.reloadCalls).toBe(0);
    expect(auth.isAnonymous()).toBe(true);
    expect(auth.status()).toBe('ready');
  });

  it('does not reload nor rewrite signals when a token refresh repeats the projection', async () => {
    const { auth, fake } = create();
    const user = createFakeUser({ emailVerified: true });
    await auth.initialize();
    fake.emitUser(user);

    const setSpy = vi.spyOn(auth.user, 'set');
    fake.emitTokenRefresh(user);
    await flush();

    expect(user.reloadCalls).toBe(0);
    expect(setSpy).not.toHaveBeenCalled();
    expect(auth.status()).toBe('ready');
  });

  it('keeps the bootstrap ready when getRedirectResult reports an error', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ emailVerified: true }));

    fake.emitRedirectError({ code: 'auth/unauthorized-domain' });
    await flush();

    expect(auth.error()).toContain('domínio');
    expect(auth.status()).toBe('ready');
    expect(auth.ready()).toBe(true);
    expect(auth.user()).not.toBeNull();
  });

  it('ignores a cancelled popup request reported by the redirect result', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ emailVerified: true }));

    fake.emitRedirectError({ code: 'auth/cancelled-popup-request' });
    await flush();

    expect(auth.error()).toBeNull();
    expect(auth.status()).toBe('ready');
  });

  it('recovers from a failed bootstrap through retryBootstrap()', async () => {
    const { auth, fake } = create();
    fake.failNextLoad(new Error('offline'));

    await auth.initialize();
    expect(auth.status()).toBe('error');
    expect(auth.ready()).toBe(true);
    expect(fake.subscriptions).toBe(0);

    const retry = auth.retryBootstrap();
    expect(auth.status()).toBe('loading');
    await retry;

    expect(fake.loadCount).toBe(2);
    fake.emitUser(createFakeUser());
    expect(auth.status()).toBe('ready');
    expect(auth.user()).not.toBeNull();
  });

  it('creates the correct SDK provider for each OAuth button', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser());

    const cases: ReadonlyArray<{
      id: 'github' | 'google' | 'apple' | 'microsoft';
      providerId: string;
      assert?: (provider: FakeOAuthProvider) => void;
    }> = [
      { id: 'github', providerId: 'github.com' },
      {
        id: 'google',
        providerId: 'google.com',
        assert: (provider) =>
          expect(provider.customParameters).toEqual({ prompt: 'select_account' }),
      },
      {
        id: 'apple',
        providerId: 'apple.com',
        assert: (provider) => expect(provider.scopes).toEqual(['email', 'name']),
      },
      {
        id: 'microsoft',
        providerId: 'microsoft.com',
        assert: (provider) => expect(provider.customParameters).toEqual({ tenant: 'common' }),
      },
    ];

    for (const testCase of cases) {
      const result = await auth.signInWithProvider(testCase.id);
      expect(result.ok).toBe(true);
      const call = fake.popupCalls.at(-1);
      expect(call?.provider.providerId).toBe(testCase.providerId);
      if (call !== undefined && testCase.assert !== undefined) {
        testCase.assert(call.provider);
      }
    }

    expect(fake.popupCalls).toHaveLength(4);
  });

  it('keeps signInWithGithub as an alias of the GitHub provider', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser());

    const result = await auth.signInWithGithub();

    expect(result.ok).toBe(true);
    expect(fake.popupCalls.at(-1)?.provider.providerId).toBe('github.com');
  });

  it('falls back to redirect only for blocked popup/unsupported environments', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser());
    fake.failNextPopup({ code: 'auth/popup-blocked' });

    const result = await auth.signInWithProvider('github');

    expect(result).toMatchObject({ ok: true, tone: 'warning' });
    expect(fake.redirectCalls).toHaveLength(1);
    expect(fake.redirectCalls[0]?.provider.providerId).toBe('github.com');
  });

  it('reports operation-not-allowed with the provider label', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser());
    fake.failNextPopup({ code: 'auth/operation-not-allowed' });

    const result = await auth.signInWithProvider('google');

    expect(result.ok).toBe(false);
    expect(result.message).toContain('Google');
    expect(result.message).toContain('não está habilitada');
  });

  it('reports a dismissed provider popup as a pt-BR cancellation', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser());
    fake.failNextPopup({ code: 'auth/popup-closed-by-user' });

    const result = await auth.signInWithProvider('google');

    expect(result.ok).toBe(false);
    expect(result.message).toBe(
      'A janela de acesso do Google foi fechada antes de concluir o acesso.',
    );
    expect(auth.error()).toBeNull();
    expect(fake.redirectCalls).toHaveLength(0);
  });

  it('refuses a provider disabled by the deployment allow-list without touching the SDK', async () => {
    const { auth, fake } = create({ ...defaultConfig, providers: ['github'] });

    const result = await auth.signInWithProvider('google');

    expect(result.ok).toBe(false);
    expect(result.message).toContain('Google');
    expect(result.message).toContain('não está habilitada');
    expect(fake.loadCount).toBe(0);
    expect(fake.popupCalls).toHaveLength(0);
  });

  it('forwards forceRefresh to the Firebase user', async () => {
    const { auth, fake } = create();
    const user = createFakeUser({ emailVerified: true });
    await auth.initialize();
    fake.emitUser(user);

    expect(await auth.getToken()).toBe('fake-id-token');
    expect(await auth.getToken(true)).toBe('fake-id-token');
    expect(user.tokenForces).toEqual([false, true]);
  });

  it('returns null for a token request without a session', async () => {
    const { auth } = create();
    await auth.initialize();
    expect(await auth.getToken(true)).toBeNull();
  });

  it('keeps the session when a manual reload fails on the network', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const user = createFakeUser({
      emailVerified: true,
      onReloadError: { code: 'auth/network-request-failed' },
    });
    fake.emitUser(user);

    const result = await auth.refreshUser({ reason: 'manual' });

    expect(result.ok).toBe(false);
    expect(auth.user()).not.toBeNull();
    expect(auth.status()).toBe('ready');
    expect(auth.ready()).toBe(true);
  });

  it('clears a disabled account and returns a pt-BR message', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const user = createFakeUser({
      emailVerified: true,
      onReloadError: { code: 'auth/user-disabled' },
    });
    fake.emitUser(user);

    const result = await auth.refreshUser({ reason: 'manual' });

    expect(result).toEqual({ ok: false, message: 'Esta conta está desativada.' });
    expect(auth.user()).toBeNull();
    expect(auth.isAuthenticated()).toBe(false);
  });

  it('throttles refreshUser return triggers for 60s unless forced', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const user = createFakeUser({ emailVerified: true });
    fake.emitUser(user);

    await auth.refreshUser({ reason: 'return' });
    await auth.refreshUser({ reason: 'return' });
    expect(user.reloadCalls).toBe(1);

    await auth.refreshUser({ reason: 'return', force: true });
    expect(user.reloadCalls).toBe(2);
  });

  it('deduplicates concurrent reloads', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const user = createFakeUser({ emailVerified: true });
    fake.emitUser(user);

    const first = auth.refreshUser({ reason: 'manual' });
    const second = auth.refreshUser({ reason: 'manual' });

    expect(second).toBe(first);
    await first;
    expect(user.reloadCalls).toBe(1);
  });

  it('stays unavailable before the bootstrap reaches the ready state', () => {
    const { auth } = create();

    expect(auth.isAuthConfigured).toBe(true);
    expect(auth.status()).toBe('idle');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('loading');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('error');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('ready');
    expect(auth.loginAvailable()).toBe(true);
  });

  it('is unavailable when the deployment carries no public configuration', () => {
    const { auth } = create({ apiKey: '', projectId: '' });

    expect(auth.isAuthConfigured).toBe(false);
    expect(auth.status()).toBe('unconfigured');
    expect(auth.loginAvailable()).toBe(false);
  });

  it('starts a guest session on demand and projects the visitor defaults', async () => {
    const { auth, fake } = create();
    await auth.initialize();

    const result = await auth.signInAnonymously();

    expect(result).toEqual({
      ok: true,
      message:
        'Sessão de visitante iniciada. Crie uma conta quando quiser para manter seu histórico.',
    });
    expect(fake.anonymousCalls).toBe(1);

    const guest = createFakeUser({
      uid: 'guest-1',
      isAnonymous: true,
      email: null,
      displayName: null,
    });
    fake.emitUser(guest);

    expect(auth.isAnonymous()).toBe(true);
    expect(auth.hasAccount()).toBe(false);
    expect(auth.displayName()).toBe('Visitante');
    expect(auth.initials()).toBe('V');
    expect(needsEmailVerification(auth.user())).toBe(false);
  });

  it('converts a guest session with e-mail by linking the credential (same uid)', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const guest = createFakeUser({
      uid: 'guest-7',
      isAnonymous: true,
      email: null,
      displayName: null,
      emailVerified: false,
    });
    fake.emitUser(guest);

    const result = await auth.signIn('ana@example.com', 'secret123');

    expect(result).toEqual({
      ok: true,
      message: 'Sessão de visitante convertida em conta. Seu histórico foi preservado.',
    });
    expect(fake.createUserCalls).toHaveLength(0);
    expect(fake.signInEmailCalls).toHaveLength(0);
    expect(fake.linkCredentialCalls).toHaveLength(1);
    expect(fake.linkCredentialCalls[0]?.user.uid).toBe('guest-7');
    expect(fake.linkCredentialCalls[0]?.credential).toMatchObject({
      providerId: 'password',
      email: 'ana@example.com',
    });

    fake.emitUser(guest);
    expect(auth.user()?.uid).toBe('guest-7');
    expect(auth.isAnonymous()).toBe(false);
  });

  it('refuses to link an e-mail that already has a sign-in method', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ uid: 'guest-8', isAnonymous: true, email: null }));
    fake.signInMethods = ['password'];

    const result = await auth.signIn('existing@example.com', 'secret123');

    expect(fake.fetchMethodsCalls).toEqual(['existing@example.com']);
    expect(fake.linkCredentialCalls).toHaveLength(0);
    expect(fake.signInEmailCalls).toHaveLength(0);
    expect(result.ok).toBe(false);
    expect(result.message).toContain('não serão migradas');
    expect(auth.isAnonymous()).toBe(true);
    expect(auth.user()?.uid).toBe('guest-8');
  });

  it('falls back to the link attempt when the sign-in methods prefetch fails', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    const guest = createFakeUser({ uid: 'guest-12', isAnonymous: true, email: null });
    fake.emitUser(guest);
    fake.failNextFetchMethods({ code: 'auth/network-request-failed' });
    fake.failNextLinkCredential({ code: 'auth/email-already-in-use' });

    const result = await auth.signIn('existing@example.com', 'secret123');

    expect(fake.fetchMethodsCalls).toEqual(['existing@example.com']);
    expect(fake.linkCredentialCalls).toHaveLength(1);
    expect(result.ok).toBe(false);
    expect(result.message).toContain('não serão migradas');
    expect(auth.isAnonymous()).toBe(true);
    expect(auth.user()?.uid).toBe('guest-12');
  });

  it('converts a guest session through an OAuth popup link', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ uid: 'guest-9', isAnonymous: true, email: null }));

    const result = await auth.signInWithProvider('google');

    expect(result.ok).toBe(true);
    expect(fake.popupCalls).toHaveLength(0);
    expect(fake.linkPopupCalls).toHaveLength(1);
    expect(fake.linkPopupCalls[0]?.user.uid).toBe('guest-9');
    expect(fake.linkPopupCalls[0]?.provider.providerId).toBe('google.com');
  });

  it('keeps the guest session when the OAuth credential belongs to another account', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ uid: 'guest-10', isAnonymous: true, email: null }));
    fake.failNextLinkPopup({ code: 'auth/credential-already-in-use' });

    const result = await auth.signInWithProvider('github');

    expect(result.ok).toBe(false);
    expect(result.message).toContain('sessão de visitante foi mantida');
    expect(fake.popupCalls).toHaveLength(0);
    expect(fake.redirectCalls).toHaveLength(0);
    expect(auth.isAnonymous()).toBe(true);
    expect(auth.user()?.uid).toBe('guest-10');
  });

  it('stores an account-exists credential and links it after the next sign-in', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.failNextPopup({
      code: 'auth/account-exists-with-different-credential',
      email: 'Ana@Example.com',
      credential: { providerId: 'google.com', signInMethod: 'google.com' },
    });

    const failed = await auth.signInWithProvider('google');

    expect(failed.ok).toBe(false);
    expect(failed.message).toContain('Google');
    expect(fake.popupCalls).toHaveLength(1);

    fake.emitUser(createFakeUser({ uid: 'user-10', email: 'ana@example.com' }));
    const login = await auth.signIn('ana@example.com', 'secret123');

    expect(login.ok).toBe(true);
    // The stored address is compared case-insensitively.
    expect(fake.linkCredentialCalls).toHaveLength(1);
    expect(fake.linkCredentialCalls[0]?.credential.providerId).toBe('google.com');
    expect(fake.linkCredentialCalls[0]?.user.uid).toBe('user-10');
  });

  it('drops the pending credential when the next sign-in uses another address', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.failNextPopup({
      code: 'auth/account-exists-with-different-credential',
      email: 'ana@example.com',
      credential: { providerId: 'google.com', signInMethod: 'google.com' },
    });
    await auth.signInWithProvider('google');

    fake.signedInUser = createFakeUser({ uid: 'user-bob', email: 'bob@example.com' });
    const login = await auth.signIn('bob@example.com', 'secret123');

    expect(login.ok).toBe(true);
    expect(fake.linkCredentialCalls).toHaveLength(0);

    // The credential was discarded, not kept for a later sign-in.
    fake.signedInUser = createFakeUser({ uid: 'user-ana', email: 'ana@example.com' });
    await auth.signIn('ana@example.com', 'secret123');
    expect(fake.linkCredentialCalls).toHaveLength(0);
  });

  it('discards the pending credential when the error carries no address', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.failNextPopup({
      code: 'auth/account-exists-with-different-credential',
      credential: { providerId: 'google.com', signInMethod: 'google.com' },
    });

    const failed = await auth.signInWithProvider('google');
    expect(failed.message).toContain('Google');

    fake.signedInUser = createFakeUser({ uid: 'user-x', email: 'ana@example.com' });
    await auth.signIn('ana@example.com', 'secret123');
    expect(fake.linkCredentialCalls).toHaveLength(0);
  });

  it('links the pending credential from the sign-in result before the observer catches up', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.failNextPopup({
      code: 'auth/account-exists-with-different-credential',
      email: 'ana@example.com',
      credential: { providerId: 'github.com', signInMethod: 'github.com' },
    });
    await auth.signInWithProvider('github');

    const account = createFakeUser({ uid: 'user-race', email: 'ana@example.com' });
    fake.signedInUser = account;
    const login = await auth.signIn('ana@example.com', 'secret123');

    expect(login.ok).toBe(true);
    // The observer has not emitted yet, so the service must use the credential
    // returned by the SDK instead of waiting for `currentUser`.
    expect(auth.user()).toBeNull();
    expect(fake.linkCredentialCalls).toHaveLength(1);
    expect(fake.linkCredentialCalls[0]?.user.uid).toBe('user-race');
  });

  it('drops the pending credential on sign out without touching the session', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ uid: 'user-11', email: 'ana@example.com' }));
    fake.failNextPopup({
      code: 'auth/account-exists-with-different-credential',
      email: 'ana@example.com',
      credential: { providerId: 'google.com', signInMethod: 'google.com' },
    });
    await auth.signInWithProvider('google');

    await auth.signOut();
    fake.emitUser(createFakeUser({ uid: 'user-12', email: 'ana@example.com' }));
    await auth.signIn('ana@example.com', 'secret123');

    expect(fake.linkCredentialCalls).toHaveLength(0);
  });

  it('arms a 60s cooldown for the verification resend', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.emitUser(createFakeUser({ emailVerified: false }));
    await flush();

    vi.useFakeTimers();
    try {
      const first = await auth.resendVerificationEmail();
      expect(first.ok).toBe(true);
      expect(auth.canResendVerification()).toBe(false);
      expect(auth.resendAvailableAt()).toBeGreaterThan(0);
      expect(auth.resendRemainingSeconds()).toBe(60);

      const second = await auth.resendVerificationEmail();
      expect(second.ok).toBe(false);
      expect(second.message).toContain('Aguarde');
      expect(fake.emailVerificationCalls).toHaveLength(1);

      vi.advanceTimersByTime(VERIFICATION_RESEND_COOLDOWN_MS);

      expect(auth.canResendVerification()).toBe(true);
      expect(auth.resendRemainingSeconds()).toBe(0);
      const third = await auth.resendVerificationEmail();
      expect(third.ok).toBe(true);
      expect(fake.emailVerificationCalls).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('reports a warning when the account is created but the verification e-mail fails', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    fake.failNextEmailVerification({ code: 'auth/network-request-failed' });

    const result = await auth.register('new@example.com', 'secret123');

    expect(result).toEqual({
      ok: true,
      tone: 'warning',
      message:
        'Conta criada, mas o e-mail de confirmação não pôde ser enviado. Use "Reenviar confirmação".',
    });
    expect(fake.createUserCalls).toHaveLength(1);
  });

  it('retries the action-code URL at the origin root when Firebase rejects it', async () => {
    const { auth, fake } = create(defaultConfig, { basePath: '/devpilot-ai' });
    await auth.initialize();
    const origin = window.location.origin;
    fake.failNextEmailVerification({ code: 'auth/unauthorized-continue-uri' });

    await auth.register('new@example.com', 'secret123');

    expect(fake.emailVerificationCalls.map((call) => call.settings?.url)).toEqual([
      `${origin}/devpilot-ai/`,
      `${origin}/`,
    ]);
    expect(
      fake.emailVerificationCalls.every((call) => call.settings?.handleCodeInApp === false),
    ).toBe(true);
  });

  it('sends the password reset with the deployment continue URL', async () => {
    const { auth, fake } = create(defaultConfig, { basePath: '/devpilot-ai' });
    await auth.initialize();
    const origin = window.location.origin;

    await auth.sendPasswordReset('ana@example.com');

    expect(fake.passwordResetCalls).toHaveLength(1);
    expect(fake.passwordResetCalls[0]?.settings?.url).toBe(`${origin}/devpilot-ai/`);
  });

  it('keeps the signed-out state when logout happens during a reload', async () => {
    const { auth, fake } = create();
    await auth.initialize();
    let release: (() => void) | undefined;
    const user = createFakeUser({
      emailVerified: true,
      onReload: () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    });
    fake.emitUser(user);

    const refreshing = auth.refreshUser({ reason: 'manual' });
    await flush();
    await auth.signOut();
    expect(auth.user()).toBeNull();

    release?.();
    await refreshing;

    expect(auth.user()).toBeNull();
    expect(auth.isAuthenticated()).toBe(false);
  });

  it('registers a single observer even when initialize is called repeatedly', async () => {
    const { auth, fake } = create();

    await Promise.all([auth.initialize(), auth.initialize(), auth.initialize()]);

    expect(fake.subscriptions).toBe(1);
    expect(fake.listeners).toHaveLength(1);
  });
});
