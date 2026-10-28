import { computed, inject, Injectable, signal } from '@angular/core';
import type { Auth, User } from 'firebase/auth';

import { ConfigService } from '../config/config.service';
import {
  AUTH_GENERIC_MESSAGE,
  AUTH_UNAVAILABLE_MESSAGE,
  authErrorCode,
  mapAuthError,
} from './auth-errors';
import { AuthResult, AuthStatus, AuthUser, initialsFor, userFromFirebase } from './auth.types';
import {
  FirebaseRuntimeConfig,
  isFirebaseConfigured,
  resolveFirebaseConfig,
} from './firebase-config';

type AuthModule = typeof import('firebase/auth');

/**
 * Firebase Authentication boundary.
 *
 * The SDK is imported dynamically (`firebase/app` and `firebase/auth`) so it
 * lives in its own lazy chunk and never inflates the initial bundle. Nothing
 * else in the app imports the SDK at runtime. The ID token is kept in memory
 * only (Firebase persists the session itself) and is refreshed through
 * `user.getIdToken()` right before each API call.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly config = inject(ConfigService);
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
  readonly email = computed(() => this.user()?.email ?? '');
  readonly displayName = computed(
    () => this.user()?.displayName ?? this.user()?.email ?? 'Visitante',
  );
  readonly initials = computed(() => initialsFor(this.user()));
  readonly emailVerified = computed(() => this.user()?.emailVerified ?? false);
  readonly available = computed(
    () => this.configured && this.status() !== 'error' && this.status() !== 'unconfigured',
  );

  private auth: Auth | null = null;
  private authApi: AuthModule | null = null;
  private currentUser: User | null = null;
  private initPromise: Promise<void> | null = null;

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

  async signIn(email: string, password: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    try {
      await this.initialize();
      const api = this.requireApi();
      await api.signInWithEmailAndPassword(this.requireAuth(), email.trim(), password);
      return { ok: true, message: 'Sessão iniciada. Bem-vindo de volta!' };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async register(email: string, password: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    try {
      await this.initialize();
      const api = this.requireApi();
      const credential = await api.createUserWithEmailAndPassword(
        this.requireAuth(),
        email.trim(),
        password,
      );
      const address = email.trim();
      try {
        await api.sendEmailVerification(credential.user);
      } catch {
        // The account exists even if the verification e-mail could not be sent;
        // the dialog offers "Reenviar" once the user is signed in.
      }
      return {
        ok: true,
        message: `Conta criada. Enviamos um link de confirmação para ${address}.`,
      };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async sendPasswordReset(email: string): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    try {
      await this.initialize();
      const api = this.requireApi();
      await api.sendPasswordResetEmail(this.requireAuth(), email.trim());
      return {
        ok: true,
        message:
          'Se existir uma conta com este e-mail, o link de redefinição chegará em instantes.',
      };
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async signInWithGithub(): Promise<AuthResult> {
    const gate = this.actionGate();
    if (gate !== null) {
      return gate;
    }
    try {
      await this.initialize();
      const api = this.requireApi();
      const auth = this.requireAuth();
      const provider = new api.GithubAuthProvider();
      try {
        await api.signInWithPopup(auth, provider);
        return { ok: true, message: 'Sessão iniciada com o GitHub.' };
      } catch (error) {
        const code = authErrorCode(error);
        if (
          code === 'auth/popup-blocked' ||
          code === 'auth/operation-not-supported-in-this-environment'
        ) {
          // Some browsers/extensions block the popup: complete the flow through
          // a full-page redirect instead.
          await api.signInWithRedirect(auth, provider);
          return { ok: true, message: 'Redirecionando para o GitHub…' };
        }
        throw error;
      }
    } catch (error) {
      return { ok: false, message: mapAuthError(error) };
    }
  }

  async resendVerificationEmail(): Promise<AuthResult> {
    if (this.currentUser === null) {
      return { ok: false, message: 'Entre na sua conta para confirmar o e-mail.' };
    }
    try {
      await this.initialize();
      await this.requireApi().sendEmailVerification(this.currentUser);
      return {
        ok: true,
        message: `Enviamos um novo link de confirmação para ${this.currentUser.email ?? 'seu e-mail'}.`,
      };
    } catch (error) {
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

  private async bootstrap(): Promise<void> {
    this.status.set('loading');
    this.error.set(null);

    try {
      const [appSdk, authSdk] = await Promise.all([
        import('firebase/app'),
        import('firebase/auth'),
      ]);
      this.authApi = authSdk;

      const app =
        appSdk.getApps().length > 0
          ? appSdk.getApp()
          : appSdk.initializeApp({ ...this.firebaseConfig });

      this.auth = authSdk.getAuth(app);

      authSdk.onAuthStateChanged(
        this.auth,
        (user) => {
          this.currentUser = user;
          this.user.set(user === null ? null : userFromFirebase(user));
          this.status.set('ready');
          this.ready.set(true);
        },
        () => {
          this.error.set('Não foi possível restaurar sua sessão. Entre novamente para continuar.');
          this.status.set('error');
          this.ready.set(true);
        },
      );

      // Popup flows blocked by the browser land here after the redirect.
      void authSdk.getRedirectResult(this.auth).catch((error: unknown) => {
        const code = authErrorCode(error);
        if (
          code !== null &&
          code !== 'auth/no-auth-event' &&
          code !== 'auth/popup-closed-by-user'
        ) {
          this.error.set(mapAuthError(error));
          this.status.set('error');
        }
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

  private actionGate(): AuthResult | null {
    if (!this.configured) {
      return { ok: false, message: AUTH_UNAVAILABLE_MESSAGE };
    }
    if (this.status() === 'error') {
      return { ok: false, message: this.error() ?? AUTH_GENERIC_MESSAGE };
    }
    return null;
  }

  private requireApi(): AuthModule {
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

  private clearUser(): void {
    this.currentUser = null;
    this.user.set(null);
  }
}
