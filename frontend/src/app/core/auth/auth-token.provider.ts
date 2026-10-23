import { InjectionToken } from '@angular/core';

export type AuthTokenProvider = () => string | null;

/**
 * Extension point for the Firebase session introduced in F5.
 *
 * The API client asks for the current bearer token immediately before every
 * request; until the auth feature provides a real token, this returns `null`
 * and anonymous submissions keep working.
 */
export const AUTH_TOKEN_PROVIDER = new InjectionToken<AuthTokenProvider>('AUTH_TOKEN_PROVIDER', {
  providedIn: 'root',
  factory: () => () => null,
});
