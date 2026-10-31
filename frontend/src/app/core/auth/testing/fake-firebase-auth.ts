import type {
  FirebaseAppSdk,
  FirebaseAuthLoader,
  FirebaseAuthSdk,
  FirebaseSdkBundle,
} from '../firebase-auth-loader';

/**
 * In-memory fake of the Firebase SDK bundle used by the auth service specs.
 *
 * It keeps the observer callbacks, exposes deterministic emitters and records
 * every provider/flow call. It deliberately avoids test-runner imports so the
 * file can live under `src/` without leaking into the production bundle.
 */

export interface FakeFirebaseUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  emailVerified: boolean;
  isAnonymous: boolean;
  reloadCalls: number;
  tokenForces: boolean[];
  reload(): Promise<void>;
  getIdToken(forceRefresh?: boolean): Promise<string>;
}

export interface FakeUserInit {
  readonly uid?: string;
  readonly email?: string | null;
  readonly displayName?: string | null;
  readonly emailVerified?: boolean;
  readonly isAnonymous?: boolean;
  /** Called inside `reload()`, so a test can simulate server-side changes. */
  readonly onReload?: (user: FakeFirebaseUser) => void | Promise<void>;
  readonly onReloadError?: unknown;
  readonly idToken?: string;
}

export function createFakeUser(init: FakeUserInit = {}): FakeFirebaseUser {
  const user: FakeFirebaseUser = {
    uid: init.uid ?? 'uid-1',
    email: init.email === undefined ? 'dev@example.com' : init.email,
    displayName: init.displayName === undefined ? 'Dev Example' : init.displayName,
    emailVerified: init.emailVerified ?? true,
    isAnonymous: init.isAnonymous ?? false,
    reloadCalls: 0,
    tokenForces: [],
    async reload(): Promise<void> {
      user.reloadCalls += 1;
      if (init.onReloadError !== undefined) {
        throw init.onReloadError;
      }
      await init.onReload?.(user);
    },
    async getIdToken(forceRefresh = false): Promise<string> {
      user.tokenForces.push(forceRefresh);
      return init.idToken ?? 'fake-id-token';
    },
  };
  return user;
}

/** Minimal OAuth provider shape shared by every fake provider class. */
export class FakeOAuthProvider {
  readonly providerId: string;
  readonly scopes: string[] = [];
  customParameters: Record<string, string> | null = null;

  constructor(providerId: string) {
    this.providerId = providerId;
  }

  addScope(scope: string): this {
    this.scopes.push(scope);
    return this;
  }

  setCustomParameters(parameters: Record<string, string>): this {
    this.customParameters = parameters;
    return this;
  }
}

export class FakeGithubAuthProvider extends FakeOAuthProvider {
  constructor() {
    super('github.com');
  }
}

export class FakeGoogleAuthProvider extends FakeOAuthProvider {
  constructor() {
    super('google.com');
  }
}

/** Credential created by `EmailAuthProvider.credential` in the fake SDK. */
export interface FakeCredential {
  readonly providerId: string;
  readonly signInMethod: string;
  readonly email?: string;
  readonly password?: string;
}

/** Settings accepted by the action-code e-mail methods. */
export interface FakeActionCodeSettings {
  readonly url?: string;
  readonly handleCodeInApp?: boolean;
}

export interface FakeListener {
  readonly next: (user: FakeFirebaseUser | null) => void;
  readonly error?: (error: unknown) => void;
}

export interface FakeFirebaseAuth {
  readonly bundle: FirebaseSdkBundle;
  readonly loader: FirebaseAuthLoader;
  readonly authInstance: { readonly name: string };
  readonly listeners: FakeListener[];
  readonly subscriptions: number;
  readonly unsubscribes: number;
  readonly loadCount: number;
  readonly popupCalls: Array<{ readonly auth: unknown; readonly provider: FakeOAuthProvider }>;
  readonly redirectCalls: Array<{ readonly auth: unknown; readonly provider: FakeOAuthProvider }>;
  readonly linkPopupCalls: Array<{
    readonly user: FakeFirebaseUser;
    readonly provider: FakeOAuthProvider;
  }>;
  readonly linkCredentialCalls: Array<{
    readonly user: FakeFirebaseUser;
    readonly credential: FakeCredential;
  }>;
  readonly signInEmailCalls: Array<{
    readonly auth: unknown;
    readonly email: string;
    readonly password: string;
  }>;
  readonly createUserCalls: Array<{
    readonly auth: unknown;
    readonly email: string;
    readonly password: string;
  }>;
  readonly fetchMethodsCalls: string[];
  readonly emailVerificationCalls: Array<{
    readonly user: FakeFirebaseUser;
    readonly settings?: FakeActionCodeSettings;
  }>;
  readonly passwordResetCalls: Array<{
    readonly auth: unknown;
    readonly email: string;
    readonly settings?: FakeActionCodeSettings;
  }>;
  readonly anonymousCalls: number;
  /** Methods returned by the next `fetchSignInMethodsForEmail` call. */
  signInMethods: string[];
  /**
   * User returned by the sign-in calls. Left `null` in most tests so the value
   * mirrors `emitUser`; a test can set it to simulate the SDK resolving before
   * the observer callback reaches the service.
   */
  signedInUser: FakeFirebaseUser | null;
  /** Rejects the next SDK load (bootstrap failure scenario). */
  failNextLoad(error: unknown): void;
  /** Rejects the next popup call (e.g. `auth/operation-not-allowed`). */
  failNextPopup(error: unknown): void;
  /** Rejects the next email/password sign-in. */
  failNextSignIn(error: unknown): void;
  /** Rejects the next `linkWithCredential`. */
  failNextLinkCredential(error: unknown): void;
  /** Rejects the next `linkWithPopup`. */
  failNextLinkPopup(error: unknown): void;
  /** Rejects the next `fetchSignInMethodsForEmail`. */
  failNextFetchMethods(error: unknown): void;
  /** Rejects the next `sendEmailVerification`. */
  failNextEmailVerification(error: unknown): void;
  /** Rejects the next `sendPasswordResetEmail`. */
  failNextPasswordReset(error: unknown): void;
  emitUser(user: FakeFirebaseUser | null): void;
  /** Token refresh: same observer channel, identical user projection. */
  emitTokenRefresh(user: FakeFirebaseUser | null): void;
  emitError(error: unknown): void;
  /** Rejects the pending `getRedirectResult` promise. */
  emitRedirectError(error: unknown): void;
  /** Resolves the pending `getRedirectResult` promise. */
  resolveRedirect(value?: unknown): void;
}

export function createFakeFirebaseAuth(): FakeFirebaseAuth {
  const listeners: FakeListener[] = [];
  const popupCalls: Array<{ auth: unknown; provider: FakeOAuthProvider }> = [];
  const redirectCalls: Array<{ auth: unknown; provider: FakeOAuthProvider }> = [];
  const linkPopupCalls: Array<{ user: FakeFirebaseUser; provider: FakeOAuthProvider }> = [];
  const linkCredentialCalls: Array<{ user: FakeFirebaseUser; credential: FakeCredential }> = [];
  const signInEmailCalls: Array<{ auth: unknown; email: string; password: string }> = [];
  const createUserCalls: Array<{ auth: unknown; email: string; password: string }> = [];
  const fetchMethodsCalls: string[] = [];
  const emailVerificationCalls: Array<{
    user: FakeFirebaseUser;
    settings?: FakeActionCodeSettings;
  }> = [];
  const passwordResetCalls: Array<{
    auth: unknown;
    email: string;
    settings?: FakeActionCodeSettings;
  }> = [];
  const authInstance = { name: 'fake-auth' };
  const appInstance = { name: '[DEFAULT]' };

  let subscriptions = 0;
  let unsubscribes = 0;
  let loadCount = 0;
  let anonymousCalls = 0;
  let signInMethods: string[] = [];
  let activeUser: FakeFirebaseUser | null = null;
  let signedInUser: FakeFirebaseUser | null = null;
  let nextLoadError: unknown = null;
  let nextPopupError: unknown = null;
  let nextSignInError: unknown = null;
  let nextLinkCredentialError: unknown = null;
  let nextLinkPopupError: unknown = null;
  let nextFetchMethodsError: unknown = null;
  let nextEmailVerificationError: unknown = null;
  let nextPasswordResetError: unknown = null;

  let redirectResolve: ((value: unknown) => void) | null = null;
  let redirectReject: ((error: unknown) => void) | null = null;
  const resetRedirect = (): Promise<unknown> =>
    new Promise<unknown>((resolve, reject) => {
      redirectResolve = resolve;
      redirectReject = reject;
    });
  let redirectPromise = resetRedirect();

  const takeError = (get: () => unknown, clear: () => void): unknown => {
    const error = get();
    if (error !== null) {
      clear();
      return error;
    }
    return null;
  };

  const appSdk = {
    getApps: () => [appInstance],
    getApp: () => appInstance,
    initializeApp: () => appInstance,
    deleteApp: async () => undefined,
  };

  const authSdk = {
    getAuth: () => authInstance,
    onIdTokenChanged: (
      _auth: unknown,
      next: (user: FakeFirebaseUser | null) => void,
      error?: (error: unknown) => void,
    ) => {
      subscriptions += 1;
      const listener: FakeListener = { next, error };
      listeners.push(listener);
      return () => {
        unsubscribes += 1;
        const index = listeners.indexOf(listener);
        if (index >= 0) {
          listeners.splice(index, 1);
        }
      };
    },
    getRedirectResult: () => redirectPromise,
    signInAnonymously: async () => {
      anonymousCalls += 1;
      return { user: signedInUser ?? activeUser, providerId: null };
    },
    signInWithPopup: async (_auth: unknown, provider: FakeOAuthProvider) => {
      popupCalls.push({ auth: _auth, provider });
      const error = takeError(
        () => nextPopupError,
        () => {
          nextPopupError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
      return { user: signedInUser ?? activeUser, providerId: provider.providerId };
    },
    signInWithRedirect: async (_auth: unknown, provider: FakeOAuthProvider) => {
      redirectCalls.push({ auth: _auth, provider });
    },
    signInWithEmailAndPassword: async (_auth: unknown, email: string, password: string) => {
      signInEmailCalls.push({ auth: _auth, email, password });
      const error = takeError(
        () => nextSignInError,
        () => {
          nextSignInError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
      return { user: signedInUser ?? activeUser, providerId: 'password' };
    },
    createUserWithEmailAndPassword: async (_auth: unknown, email: string, password: string) => {
      createUserCalls.push({ auth: _auth, email, password });
      return { user: createFakeUser({ email }), providerId: 'password' };
    },
    linkWithPopup: async (user: FakeFirebaseUser, provider: FakeOAuthProvider) => {
      linkPopupCalls.push({ user, provider });
      const error = takeError(
        () => nextLinkPopupError,
        () => {
          nextLinkPopupError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
      user.isAnonymous = false;
      return { user, providerId: provider.providerId };
    },
    linkWithCredential: async (user: FakeFirebaseUser, credential: FakeCredential) => {
      linkCredentialCalls.push({ user, credential });
      const error = takeError(
        () => nextLinkCredentialError,
        () => {
          nextLinkCredentialError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
      if (credential.providerId === 'password' && credential.email !== undefined) {
        user.email = credential.email;
        user.isAnonymous = false;
      }
      return { user, providerId: credential.providerId };
    },
    fetchSignInMethodsForEmail: async (_auth: unknown, email: string) => {
      fetchMethodsCalls.push(email);
      const error = takeError(
        () => nextFetchMethodsError,
        () => {
          nextFetchMethodsError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
      return [...signInMethods];
    },
    sendEmailVerification: async (user: FakeFirebaseUser, settings?: FakeActionCodeSettings) => {
      emailVerificationCalls.push({ user, settings });
      const error = takeError(
        () => nextEmailVerificationError,
        () => {
          nextEmailVerificationError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
    },
    sendPasswordResetEmail: async (
      _auth: unknown,
      email: string,
      settings?: FakeActionCodeSettings,
    ) => {
      passwordResetCalls.push({ auth: _auth, email, settings });
      const error = takeError(
        () => nextPasswordResetError,
        () => {
          nextPasswordResetError = null;
        },
      );
      if (error !== null) {
        throw error;
      }
    },
    signOut: async () => undefined,
    EmailAuthProvider: {
      credential: (email: string, password: string): FakeCredential => ({
        providerId: 'password',
        signInMethod: 'password',
        email,
        password,
      }),
    },
    GithubAuthProvider: FakeGithubAuthProvider,
    GoogleAuthProvider: FakeGoogleAuthProvider,
    OAuthProvider: FakeOAuthProvider,
  };

  const bundle: FirebaseSdkBundle = {
    app: appSdk as unknown as FirebaseAppSdk,
    auth: authSdk as unknown as FirebaseAuthSdk,
  };

  const loader: FirebaseAuthLoader = async () => {
    loadCount += 1;
    const error = takeError(
      () => nextLoadError,
      () => {
        nextLoadError = null;
      },
    );
    if (error !== null) {
      throw error;
    }
    return bundle;
  };

  return {
    bundle,
    loader,
    authInstance,
    listeners,
    get subscriptions() {
      return subscriptions;
    },
    get unsubscribes() {
      return unsubscribes;
    },
    get loadCount() {
      return loadCount;
    },
    popupCalls,
    redirectCalls,
    linkPopupCalls,
    linkCredentialCalls,
    signInEmailCalls,
    createUserCalls,
    fetchMethodsCalls,
    emailVerificationCalls,
    passwordResetCalls,
    get anonymousCalls() {
      return anonymousCalls;
    },
    get signInMethods() {
      return signInMethods;
    },
    set signInMethods(methods: string[]) {
      signInMethods = [...methods];
    },
    get signedInUser() {
      return signedInUser;
    },
    set signedInUser(user: FakeFirebaseUser | null) {
      signedInUser = user;
    },
    failNextLoad(error: unknown): void {
      nextLoadError = error;
    },
    failNextPopup(error: unknown): void {
      nextPopupError = error;
    },
    failNextSignIn(error: unknown): void {
      nextSignInError = error;
    },
    failNextLinkCredential(error: unknown): void {
      nextLinkCredentialError = error;
    },
    failNextLinkPopup(error: unknown): void {
      nextLinkPopupError = error;
    },
    failNextFetchMethods(error: unknown): void {
      nextFetchMethodsError = error;
    },
    failNextEmailVerification(error: unknown): void {
      nextEmailVerificationError = error;
    },
    failNextPasswordReset(error: unknown): void {
      nextPasswordResetError = error;
    },
    emitUser(user: FakeFirebaseUser | null): void {
      activeUser = user;
      for (const listener of [...listeners]) {
        listener.next(user);
      }
    },
    emitTokenRefresh(user: FakeFirebaseUser | null): void {
      activeUser = user;
      for (const listener of [...listeners]) {
        listener.next(user);
      }
    },
    emitError(error: unknown): void {
      for (const listener of [...listeners]) {
        listener.error?.(error);
      }
    },
    emitRedirectError(error: unknown): void {
      redirectReject?.(error);
      // Allow a later assertion of a second redirect event to start clean.
      redirectPromise = resetRedirect();
    },
    resolveRedirect(value: unknown = null): void {
      redirectResolve?.(value);
      redirectPromise = resetRedirect();
    },
  };
}
