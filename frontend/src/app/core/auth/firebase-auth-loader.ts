import { InjectionToken } from '@angular/core';

/**
 * Type-only view of the dynamically imported Firebase SDKs.
 *
 * `typeof import('firebase/app')` and `typeof import('firebase/auth')` are
 * type queries: they are erased at build time, so this module introduces no
 * static runtime dependency on the SDK. The only runtime import of Firebase
 * happens through the loader factory below, which keeps `firebase/app` and
 * `firebase/auth` in their own lazy chunk.
 */
export type FirebaseAppSdk = typeof import('firebase/app');
export type FirebaseAuthSdk = typeof import('firebase/auth');

/** Alias kept for callers/tests that prefer the shorter name. */
export type FAuthGuardSdk = FirebaseAuthSdk;

export interface FirebaseSdkBundle {
  readonly app: FirebaseAppSdk;
  readonly auth: FirebaseAuthSdk;
}

/** Resolves the lazy Firebase SDK bundle. */
export type FirebaseAuthLoader = () => Promise<FirebaseSdkBundle>;

/** Loads both Firebase entry points in parallel (single lazy chunk). */
export function loadFirebaseSdk(): Promise<FirebaseSdkBundle> {
  return Promise.all([import('firebase/app'), import('firebase/auth')]).then(([app, auth]) => ({
    app,
    auth,
  }));
}

/**
 * Seam that lets the auth service (and tests) obtain the Firebase SDK without
 * importing it statically. Tests replace it with an in-memory fake.
 */
export const FIREBASE_AUTH_LOADER = new InjectionToken<FirebaseAuthLoader>('FIREBASE_AUTH_LOADER', {
  providedIn: 'root',
  factory: () => loadFirebaseSdk,
});
