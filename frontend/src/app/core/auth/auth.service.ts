import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';
import type {
  ActionCodeSettings,
  Auth,
  AuthCredential,
  AuthProvider,
  Unsubscribe,
  User,
} from 'firebase/auth';

import { ConfigService } from '../config/config.service';
import {
  buildActionCodeSettings,
  buildFallbackActionCodeSettings,
  isContinueUriRejection,
} from './action-code-settings';
import {
  AUTH_GENERIC_MESSAGE,
  AUTH_UNAVAILABLE_MESSAGE,
  authErrorCode,
  emailFromAuthError,
  mapAuthError,
  pendingCredentialFrom,
} from './auth-errors';
import {
  enabledAuthProviders,
  findAuthProvider,
  providerLabelForMethod,
  type OAuthProviderId,
} from './auth-providers';
import {
  AuthResult,
  AuthStatus,
  AuthUser,
  initialsFor,
  sameAuthUser,
  userFromFirebase,
} from './auth.types';
import {
  FIREBASE_AUTH_LOADER,
  type FirebaseAuthSdk,
  type FirebaseSdkBundle,
} from './firebase-auth-loader';
import {
  FirebaseRuntimeConfig,
  isFirebaseConfigured,
  resolveFirebaseConfig,
} from './firebase-config';

export type RefreshReason = 'boot' | 'return' | 'manual';

export interface RefreshUserOptions {
  readonly force?: boolean;
  readonly reason?: RefreshReason;
}

export interface RefreshUserResult {
  readonly ok: boolean;
  readonly message?: string;
}

/**
 * Credential held between the `account-exists-with-different-credential`
 * failure and the next successful sign-in.
 *
 * The address carried by the error is stored together with the credential so
 * the link only happens on the account that actually owns that address.
 */
interface PendingCredential {
  readonly credential: AuthCredential;
  readonly email: string;
}

/** Normalizes an address for case-insensitive comparison. */
function normalizeEmail(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase();
}

/** Minimum interval between `reason: 'return'` refreshes (unless forced). */
const RETURN_REFRESH_THROTTLE_MS = 60_000;

/** Minimum interval between two verification e-mails for the same session. */
export const VERIFICATION_RESEND_COOLDOWN_MS = 60_000;

const GUEST_SESSION_MESSAGE =
  'Sessão de visitante iniciada. Crie uma conta quando quiser para manter seu histórico.';

const GUEST_CONVERTED_MESSAGE =
  'Sessão de visitante convertida em conta. Seu histórico foi preservado.';

const GUEST_EMAIL_CONFLICT_MESSAGE =
  'Este e-mail já tem uma conta. Saia da sessão de visitante e entre na conta existente — as análises de visitante não serão migradas.';

const GUEST_PROVIDER_CONFLICT_MESSAGE =
  'Este e-mail já está vinculado a outra conta. Sua sessão de visitante foi mantida — saia dela e entre na conta existente; as análises de visitante não serão migradas.';

const REGISTER_VERIFICATION_FAILED_MESSAGE =
  'Conta criada, mas o e-mail de confirmação não pôde ser enviado. Use "Reenviar confirmação".';

/**
 * Redirect results that do not represent a failed sign-in attempt: no pending
 * event, or the user dismissed/cancelled the popup. Surfacing them would add an
 * error banner over a perfectly usable session.
 */
const IGNORED_REDIRECT_CODES: ReadonlySet<string> = new Set([
  'auth/no-auth-event',
  'auth/popup-closed-by-user',
  'auth/cancelled-popup-request',
]);

/**
 * Firebase Authentication boundary.
 *
 * The SDK is imported dynamically through `FIREBASE_AUTH_LOADER` so it lives
 * in its own lazy chunk and never inflates the initial bundle. Nothing else in
 * the app imports the SDK at runtime. The ID token is kept in memory only
 * (Firebase persists the session itself) and is refreshed through
 * `user.getIdToken()` right before each API call.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly config = inject(ConfigService);
  private readonly loader = inject(FIREBASE_AUTH_LOADER);
  private readonly destroyRef = inject(DestroyRef);
  private readonly firebaseConfig: FirebaseRuntimeConfig = resolveFirebaseConfig(
    this.config.firebase,
  );

  /** False when the deployment carries no public Firebase configuration. */
  readonly configured = isFirebaseConfigured(this.firebaseConfig);
  /** Named guard used by login entry points. */
  readonly isAuthConfigured = this.configured;
  /**
   * True only when the SDK finished bootstrapping without an error.
   *
   * `isAuthConfigured` is static (the deployment carries public config), but
   * the flow is still unusable while the SDK is loading or after the bootstrap
   * failed (for example an invalid api key or a blocked network). Login entry
   * points use this signal to avoid opening a form that cannot authenticate.
   */
  readonly loginAvailable = computed(() => this.configured && this.status() === 'ready');

  readonly status = signal<AuthStatus>(this.configured ? 'idle' : 'unconfigured');
  /** True once the session was restored (or definitively dismissed). */
  readonly ready = signal(!this.configured);
  readonly user = signal<AuthUser | null>(null);
  readonly error = signal<string | null>(null);

  readonly isAuthenticated = computed(() => this.user() !== null);
  readonly isAnonymous = computed(() => this.user()?.isAnonymous ?? false);
  /** True for a real account (not a guest/anonymous session). */
  readonly hasAccount = computed(() => this.isAuthenticated() && !this.isAnonymous());
  readonly email = computed(() => this.user()?.email ?? '');
  readonly displayName = computed(
    () => this.user()?.displayName ?? this.user()?.email ?? 'Visitante',
  );
  readonly initials = computed(() => initialsFor(this.user()));
  readonly emailVerified = computed(() => this.user()?.emailVerified ?? false);
  readonly available = computed(
    () => this.configured && this.status() !== 'error' && this.status() !== 'unconfigured',
  );
  /** OAuth providers enabled for this deployment (all when unspecified). */
  readonly providers = computed(() => enabledAuthProviders(this.firebaseConfig.providers));

  /**
   * Moment (epoch ms) after which another verification e-mail may be sent.
   * `0` means "no cooldown armed".
   */
  readonly resendAvailableAt = signal(0);
  private readonly clock = signal(Date.now());
  /** Reactive guard for the resend action (the UI mirrors it as a countdown). */
  readonly canResendVerification = computed(() => this.clock() >= this.resendAvailableAt());
  /**
   * Whole seconds left in the resend cooldown (`0` when it may be resent).
   *
   * The dialog reads this instead of owning a second interval: one shared clock
   * drives every countdown in the app.
   */
  readonly resendRemainingSeconds = computed(() => {
    const remaining = this.resendAvailableAt() - this.clock();
    return remaining > 0 ? Math.ceil(remaining / 1_000) : 0;
  });

  private auth: Auth | null = null;
  private authApi: FirebaseAuthSdk | null = null;
  private currentUser: User | null = null;
  private initPromise: Promise<void> | null = null;
  private unsubscribe: Unsubscribe | null = null;
  private firstEmissionHandled = false;
  private reloadInFlight: Promise<RefreshUserResult> | null = null;
  private lastReturnRefreshAt = 0;
  private cooldownTimer: ReturnType<typeof setInterval> | null = null;
  /**
   * Credential from `account-exists-with-different-credential`, kept in memory
   * only and linked right after the next successful sign-in on the same address.
   */
  private pendingCredential: PendingCredential | null = null;

  constructor() {
    // The observer must not outlive the injector (tests, HMR, SSR teardown).
    this.destroyRef.onDestroy(() => {
      this.unsubscribe?.();
      this.unsubscribe = null;
      this.stopCooldownTimer();
    });
  }

  /** Loads the SDK, restores the session and keeps the observer registered. */
  initialize(): Promise<void> {
    if (!this.configured) {
      this.status.set('unconfigured');
      this.ready.set(true);
      return Promise.resolve();
    }
    if (this.initPromise !== null) {
      return this.initPromise;
    }
    this.initPromise = this.bootstrap();
    return this.initPromise;
  }

  /**
   * Discards the failed bootstrap and starts it again.
   *
   * Used by the dialog's "Tentar novamente" action after a terminal bootstrap
   * error (invalid key, blocked network). The observer is released first so a
   * new registration never leaves a stale listener behind.
   */
  retryBootstrap(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.initPromise = null;
    this.firstEmissionHandled = false;
    this.status.set('idle');
    this.ready.set(false);
    this.error.set(null);
    return this.initialize();
  }

  /** Current ID token, or `null` for a visitor (or after a refresh failure). */
  async getToken(forceRefresh = false): Promise<string | null> {
    const user = this.currentUser;
    if (user === null) {
      return null;
    }
    try {
      return await user.getIdToken(forceRefresh);
    } catch {
      // An unrecoverable token is treated as "no session"; the API answers 401
      // and the history flow asks for a new login.
      return null;
    }
  }

  /**
   * Starts a guest session (opt-in only: it never runs automatically on boot).
   *
   * A guest has access to the same anonymous analyses as a visitor; creating a
   * real account later converts this session through `linkWithCredential`,
   * preserving the same uid (and therefore the same history scope).
   */
  async signInAnonymously(): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    try {
      await this.initialize();
      await this.requireApi().signInAnonymously(this.requireAuth());
      return { ok: true, message: GUEST_SESSION_MESSAGE };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async signIn(email: string, password: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    const address = email.trim();
    try {
      await this.initialize();
      const api = this.requireApi();
      const user = this.currentUser;
      if (user !== null && user.isAnonymous) {
        return await this.convertGuestWithEmail(user, address, password, false);
      }
      const credential = await api.signInWithEmailAndPassword(
        this.requireAuth(),
        address,
        password,
      );
      await this.attachPendingCredential(credential.user);
      return { ok: true, message: 'Sessão iniciada. Bem-vindo de volta!' };
    } catch (error) {
      const pending = this.rememberPendingCredential(error);
      return { ok: false, message: pending ?? mapAuthError(error) };
    }
  }

  async register(email: string, password: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    const address = email.trim();
    try {
      await this.initialize();
      const api = this.requireApi();
      const user = this.currentUser;
      if (user !== null && user.isAnonymous) {
        return await this.convertGuestWithEmail(user, address, password, true);
      }
      const credential = await api.createUserWithEmailAndPassword(
        this.requireAuth(),
        address,
        password,
      );
      return await this.afterRegistration(credential.user, address);
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  /**
   * Converts the current guest session into an e-mail/password account.
   *
   * The credential is *linked* to the existing anonymous user, so the uid (and
   * the analyses already owned by it) is preserved. When the address already
   * belongs to an account the link is refused and the guest session is kept:
   * signing into the existing account would silently abandon the guest history.
   */
  private async convertGuestWithEmail(
    guest: User,
    address: string,
    password: string,
    registration: boolean,
  ): Promise<AuthResult> {
    const conflict = await this.existingAccountConflict(address);
    if (conflict !== null) {
      return conflict;
    }

    const api = this.requireApi();
    try {
      await api.linkWithCredential(guest, api.EmailAuthProvider.credential(address, password));
    } catch (error) {
      if (authErrorCode(error) === 'auth/email-already-in-use') {
        return { ok: false, message: GUEST_EMAIL_CONFLICT_MESSAGE };
      }
      throw error;
    }

    if (registration) {
      return this.afterRegistration(
        guest,
        address,
        `Conta criada e vinculada à sua sessão de visitante. Enviamos um link de confirmação para ${address}.`,
      );
    }
    return { ok: true, message: GUEST_CONVERTED_MESSAGE };
  }

  /**
   * `fetchSignInMethodsForEmail` before linking: a non-empty list means the
   * address already has a way to sign in, so the guest must not take it over.
   *
   * The prefetch is best effort: when it fails (network, disabled API) the
   * conversion proceeds and `linkWithCredential` still refuses an address in
   * use with `auth/email-already-in-use`.
   */
  private async existingAccountConflict(address: string): Promise<AuthResult | null> {
    let methods: string[];
    try {
      methods = await this.requireApi().fetchSignInMethodsForEmail(this.requireAuth(), address);
    } catch {
      return null;
    }
    if (methods.length === 0) {
      return null;
    }
    const labels = methods.map(providerLabelForMethod).join(', ');
    return {
      ok: false,
      message: `${GUEST_EMAIL_CONFLICT_MESSAGE} Método atual: ${labels}.`,
    };
  }

  /** Sends the verification e-mail and reports a warning when it fails. */
  private async afterRegistration(
    user: User,
    address: string,
    successMessage = `Conta criada. Enviamos um link de confirmação para ${address}.`,
  ): Promise<AuthResult> {
    try {
      await this.sendVerification(user);
      this.armResendCooldown();
      return { ok: true, message: successMessage };
    } catch (error) {
      if (authErrorCode(error) === 'auth/too-many-requests') {
        this.armResendCooldown();
      }
      return { ok: true, tone: 'warning', message: REGISTER_VERIFICATION_FAILED_MESSAGE };
    }
  }

  async sendPasswordReset(email: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    const address = email.trim();
    try {
      await this.initialize();
      await this.withActionCodeSettings((settings) => {
        const api = this.requireApi();
        return settings === undefined
          ? api.sendPasswordResetEmail(this.requireAuth(), address)
          : api.sendPasswordResetEmail(this.requireAuth(), address, settings);
      });
      return {
        ok: true,
        message:
          'Se existir uma conta com este e-mail, o link de redefinição chegará em instantes.',
      };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  /**
   * Starts the popup flow for one of the registered OAuth providers.
   *
   * With an active guest session the provider is *linked* to the anonymous user
   * instead of replacing the session, so the uid is preserved. A conflict with
   * an existing account never swaps accounts automatically.
   */
  async signInWithProvider(id: OAuthProviderId): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    const definition = findAuthProvider(id);
    if (definition === null) {
      return { ok: false, message: AUTH_GENERIC_MESSAGE };
    }
    if (!this.isProviderEnabled(id)) {
      return {
        ok: false,
        message: `A entrada com ${definition.label} não está habilitada neste ambiente.`,
      };
    }

    const label = definition.label;
    try {
      await this.initialize();
      const api = this.requireApi();
      const auth = this.requireAuth();
      const provider = definition.create(api);
      const user = this.currentUser;
      if (user !== null && user.isAnonymous) {
        return await this.linkGuestProvider(user, provider, label);
      }

      let signedIn: User | null = null;
      try {
        const credential = await api.signInWithPopup(auth, provider);
        signedIn = credential.user;
      } catch (error) {
        const code = authErrorCode(error);
        if (
          code === 'auth/popup-blocked' ||
          code === 'auth/operation-not-supported-in-this-environment'
        ) {
          // Some browsers/extensions block the popup: complete the flow through
          // a full-page redirect instead.
          await api.signInWithRedirect(auth, provider);
          return {
            ok: true,
            message: `Redirecionando para ${label}…`,
            tone: 'warning',
          };
        }
        const pending = this.rememberPendingCredential(error);
        if (pending !== null) {
          return { ok: false, message: pending };
        }
        throw error;
      }
      await this.attachPendingCredential(signedIn);
      return { ok: true, message: `Sessão iniciada com ${label}.` };
    } catch (error) {
      return { ok: false, message: mapAuthError(error, { providerLabel: label }) };
    }
  }

  private async linkGuestProvider(
    guest: User,
    provider: AuthProvider,
    label: string,
  ): Promise<AuthResult> {
    const api = this.requireApi();
    try {
      await api.linkWithPopup(guest, provider);
      return {
        ok: true,
        message: `Conta vinculada ao ${label}. Seu histórico de visitante foi preservado.`,
      };
    } catch (error) {
      const code = authErrorCode(error);
      if (
        code === 'auth/credential-already-in-use' ||
        code === 'auth/account-exists-with-different-credential'
      ) {
        return { ok: false, message: GUEST_PROVIDER_CONFLICT_MESSAGE };
      }
      if (
        code === 'auth/popup-blocked' ||
        code === 'auth/operation-not-supported-in-this-environment'
      ) {
        return {
          ok: false,
          message: `O navegador bloqueou a janela do ${label}. Permita pop-ups para vincular a conta.`,
        };
      }
      throw error;
    }
  }

  /** Backwards-compatible alias for the GitHub popup flow. */
  signInWithGithub(): Promise<AuthResult> {
    return this.signInWithProvider('github');
  }

  async resendVerificationEmail(): Promise<AuthResult> {
    if (this.currentUser === null) {
      return { ok: false, message: 'Entre na sua conta para confirmar o e-mail.' };
    }
    if (!this.canResendVerification()) {
      return { ok: false, message: this.cooldownMessage() };
    }
    try {
      await this.initialize();
      await this.sendVerification(this.currentUser);
      this.armResendCooldown();
      return {
        ok: true,
        message: `Enviamos um novo link de confirmação para ${this.currentUser.email ?? 'seu e-mail'}.`,
      };
    } catch (error) {
      if (authErrorCode(error) === 'auth/too-many-requests') {
        this.armResendCooldown();
      }
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async signOut(): Promise<AuthResult> {
    if (!this.configured) {
      this.clearUser();
      return { ok: true, message: 'Você saiu da sua conta.' };
    }
    try {
      await this.initialize();
      if (this.auth !== null && this.authApi !== null) {
        await this.authApi.signOut(this.auth);
      }
      this.clearUser();
      return { ok: true, message: 'Você saiu da sua conta.' };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  /**
   * Reloads the current Firebase user to pick up server-side changes (for
   * example the e-mail confirmation), deduplicating concurrent calls.
   *
   * Network failures return `{ ok: false }` without touching the session state;
   * a disabled/removed account is cleared and reports a pt-BR message. Only
   * `reason: 'return'` is throttled, and `force` bypasses that throttle.
   */
  refreshUser(options: RefreshUserOptions = {}): Promise<RefreshUserResult> {
    const user = this.currentUser;
    if (user === null) {
      return Promise.resolve({ ok: true });
    }

    const force = options.force === true;
    const reason = options.reason ?? 'manual';
    if (reason === 'return' && !force) {
      const now = Date.now();
      if (now - this.lastReturnRefreshAt < RETURN_REFRESH_THROTTLE_MS) {
        return Promise.resolve({ ok: true });
      }
      this.lastReturnRefreshAt = now;
    }

    if (this.reloadInFlight !== null) {
      return this.reloadInFlight;
    }

    const task = this.reloadCurrentUser(user).finally(() => {
      this.reloadInFlight = null;
    });
    this.reloadInFlight = task;
    return task;
  }

  /**
   * Drops a session the API rejected with `401`.
   *
   * The Firebase observer is signed out locally (no network) so the UI returns
   * to the visitor state; the caller decides how to ask for a new login.
   */
  expireSession(): void {
    this.clearUser();
    if (this.auth !== null && this.authApi !== null) {
      void this.authApi.signOut(this.auth).catch(() => undefined);
    }
  }

  private async reloadCurrentUser(user: User): Promise<RefreshUserResult> {
    try {
      await user.reload();
      if (this.currentUser === user) {
        this.applyProjection(userFromFirebase(user));
      }
      return { ok: true };
    } catch (error) {
      const code = authErrorCode(error);
      if (code === 'auth/user-disabled' || code === 'auth/user-not-found') {
        this.clearUser();
        return { ok: false, message: mapAuthError(error) };
      }
      return { ok: false };
    }
  }

  private async bootstrap(): Promise<void> {
    this.status.set('loading');
    this.error.set(null);
    this.firstEmissionHandled = false;

    try {
      const sdk = await this.loadSdk();
      this.authApi = sdk.auth;

      const app =
        sdk.app.getApps().length > 0 ? sdk.app.getApp() : sdk.app.initializeApp(this.sdkConfig());

      this.auth = sdk.auth.getAuth(app);

      this.unsubscribe?.();
      this.unsubscribe = sdk.auth.onIdTokenChanged(
        this.auth,
        (user) => this.handleUser(user),
        () => this.handleObserverError(),
      );

      // Popup flows blocked by the browser land here after the redirect.
      void sdk.auth.getRedirectResult(this.auth).catch((error: unknown) => {
        this.handleRedirectError(error);
      });
    } catch (error) {
      this.error.set(
        'Não foi possível carregar o serviço de autenticação. Verifique sua conexão e tente novamente.',
      );
      if (authErrorCode(error) === 'auth/invalid-api-key') {
        this.error.set(mapAuthError(error));
      }
      this.status.set('error');
      this.ready.set(true);
    }
  }

  private loadSdk(): Promise<FirebaseSdkBundle> {
    return this.loader();
  }

  /** Firebase config without the app-only provider allow-list. */
  private sdkConfig(): FirebaseRuntimeConfig {
    const { providers: _providers, ...config } = this.firebaseConfig;
    return config;
  }

  private handleUser(user: User | null): void {
    this.currentUser = user;
    this.applyProjection(user === null ? null : userFromFirebase(user));

    if (user === null) {
      // Signed out in this tab (or another one): the memory-only pending
      // credential and the resend cooldown no longer belong to a session.
      this.clearTransientState();
    }

    if (!this.firstEmissionHandled) {
      this.firstEmissionHandled = true;
      this.status.set('ready');
      this.ready.set(true);
      // A restored account that has not confirmed the e-mail yet gets exactly
      // one silent refresh so the verified badge catches up without a manual
      // action. It is scheduled out of the observer callback on purpose: the
      // SDK must never be reloaded from inside its own emission. Guests have no
      // verified e-mail to catch up with, so they never trigger the extra call.
      if (user !== null && !user.isAnonymous && !user.emailVerified) {
        void Promise.resolve().then(() => this.refreshUser({ reason: 'boot' }));
      }
    }
  }

  private handleObserverError(): void {
    this.error.set('Não foi possível restaurar sua sessão. Entre novamente para continuar.');
    this.status.set('error');
    this.ready.set(true);
  }

  private handleRedirectError(error: unknown): void {
    const code = authErrorCode(error);
    if (code === null || IGNORED_REDIRECT_CODES.has(code)) {
      return;
    }
    // Redirect failures are surfaced as a notice, but the session is still
    // usable: the bootstrap status stays `ready` so the retry dialog works.
    this.error.set(mapAuthError(error));
  }

  private applyProjection(next: AuthUser | null): void {
    if (sameAuthUser(this.user(), next)) {
      return;
    }
    this.user.set(next);
  }

  private isProviderEnabled(id: OAuthProviderId): boolean {
    const definition = findAuthProvider(id);
    return definition !== null && (definition.enabled?.(this.firebaseConfig.providers) ?? true);
  }

  private actionGate(): AuthResult | null {
    if (!this.configured) {
      return { ok: false, message: AUTH_UNAVAILABLE_MESSAGE };
    }
    if (this.status() === 'error') {
      return { ok: false, message: this.error() ?? AUTH_GENERIC_MESSAGE };
    }
    return null;
  }

  private requireApi(): FirebaseAuthSdk {
    if (this.authApi === null) {
      throw new Error('Firebase Auth não inicializado.');
    }
    return this.authApi;
  }

  private requireAuth(): Auth {
    if (this.auth === null) {
      throw new Error('Firebase Auth não inicializado.');
    }
    return this.auth;
  }

  /** Sends the verification e-mail with the deployment's continue URL. */
  private sendVerification(user: User): Promise<void> {
    return this.withActionCodeSettings((settings) => {
      const api = this.requireApi();
      return settings === undefined
        ? api.sendEmailVerification(user)
        : api.sendEmailVerification(user, settings);
    });
  }

  /**
   * Runs an action-code e-mail call with `ActionCodeSettings`, retrying once at
   * the origin root when Firebase rejects the configured continue URL.
   */
  private async withActionCodeSettings(
    action: (settings?: ActionCodeSettings) => Promise<void>,
  ): Promise<void> {
    const settings = this.actionCodeSettings();
    if (settings === null) {
      await action();
      return;
    }
    try {
      await action(settings);
    } catch (error) {
      if (!isContinueUriRejection(authErrorCode(error))) {
        throw error;
      }
      await action(this.fallbackActionCodeSettings() ?? undefined);
    }
  }

  private actionCodeSettings(): ActionCodeSettings | null {
    const origin = this.origin();
    return origin === '' ? null : buildActionCodeSettings(origin, this.config.basePath ?? '');
  }

  private fallbackActionCodeSettings(): ActionCodeSettings | null {
    const origin = this.origin();
    return origin === '' ? null : buildFallbackActionCodeSettings(origin);
  }

  private origin(): string {
    return (globalThis.location?.origin ?? '').trim();
  }

  /**
   * Links the pending credential only when the account that just signed in owns
   * the address carried by the original error.
   *
   * Without that check a Google attempt for `ana@example.com` followed by a
   * login as `bob@example.com` would attach Ana's identity to Bob's account.
   * A divergence (or an address we cannot compare) simply discards the
   * credential. The "already linked" conflicts are ignored; any other failure
   * is dropped because the credential is memory-only and never blocks the
   * session the user just opened.
   */
  private async attachPendingCredential(signedIn: User | null = null): Promise<void> {
    const pending = this.pendingCredential;
    this.pendingCredential = null;
    const user = signedIn ?? this.currentUser;
    if (pending === null || user === null || user.isAnonymous) {
      return;
    }
    const target = normalizeEmail(user.email);
    if (target === '' || target !== normalizeEmail(pending.email)) {
      return;
    }
    try {
      await this.requireApi().linkWithCredential(user, pending.credential);
    } catch (error) {
      const code = authErrorCode(error);
      if (code === 'auth/provider-already-linked' || code === 'auth/credential-already-in-use') {
        return;
      }
    }
  }

  /**
   * Stores the credential carried by `account-exists-with-different-credential`
   * (together with the address it belongs to) and returns the orientation
   * message, or `null` for any other error.
   *
   * Without the address there is nothing safe to link later, so the message is
   * still shown but no pending credential is kept.
   */
  private rememberPendingCredential(error: unknown): string | null {
    if (authErrorCode(error) !== 'auth/account-exists-with-different-credential') {
      return null;
    }
    const credential = pendingCredentialFrom(error);
    if (credential === null) {
      return null;
    }
    const email = normalizeEmail(emailFromAuthError(error));
    this.pendingCredential = email === '' ? null : { credential, email };
    const method = providerLabelForMethod(credential.providerId || credential.signInMethod);
    return `Este e-mail já usa ${method}. Entre com ${method} para acessar a conta; o novo acesso será vinculado automaticamente após o login.`;
  }

  /** Arms the resend cooldown and ticks the reactive clock once per second. */
  private armResendCooldown(): void {
    const until = Date.now() + VERIFICATION_RESEND_COOLDOWN_MS;
    this.resendAvailableAt.set(until);
    this.clock.set(Date.now());
    this.stopCooldownTimer();
    this.cooldownTimer = setInterval(() => {
      const now = Date.now();
      this.clock.set(now);
      if (now >= until) {
        this.stopCooldownTimer();
      }
    }, 1_000);
  }

  private stopCooldownTimer(): void {
    if (this.cooldownTimer !== null) {
      clearInterval(this.cooldownTimer);
      this.cooldownTimer = null;
    }
  }

  private resetCooldown(): void {
    this.stopCooldownTimer();
    this.resendAvailableAt.set(0);
    this.clock.set(Date.now());
  }

  private cooldownMessage(): string {
    const remaining = Math.max(1, Math.ceil((this.resendAvailableAt() - Date.now()) / 1_000));
    return `Aguarde ${remaining}s para reenviar a confirmação.`;
  }

  private clearTransientState(): void {
    this.pendingCredential = null;
    this.resetCooldown();
  }

  private clearUser(): void {
    this.currentUser = null;
    this.user.set(null);
    this.clearTransientState();
  }
}
