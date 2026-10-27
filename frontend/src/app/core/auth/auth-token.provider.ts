import { InjectionToken } from '@angular/core';

/**
 * Returns the current bearer token, or `null` for an anonymous request.
 *
 * Firebase refreshes an ID token shortly before it expires, so the API client
 * asks for the token immediately before every request instead of caching one.
 */
export type AuthTokenProvider = () => Promise<string | null>;

/**
 * Extension point for the Firebase session introduced in F5.
 *
 * Until the auth feature provides a real token, this resolves to `null` and
 * anonymous submissions keep working. `F5` overrides it in `app.config.ts`
 * with the `AuthService` token getter.
 */
export const AUTH_TOKEN_PROVIDER = new InjectionToken<AuthTokenProvider>('AUTH_TOKEN_PROVIDER', {
  providedIn: 'root',
  factory: () => async () => null,
});
