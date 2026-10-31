import type { ActionCodeSettings } from 'firebase/auth';

import { normalizeBasePath } from '../config/app-config';

/**
 * Redirect target for Firebase action e-mails (verification and password reset).
 *
 * Firebase requires an absolute URL listed under *Authentication → Settings →
 * Authorized domains*. The SPA is a hash-routed application served from a
 * sub-path, so the URL only needs to land on the deployed index; the SDK appends
 * its own `mode`/`oobCode` query parameters (the hash is preserved). The trailing
 * slash keeps `https://host/sub-path/` a valid static document on GitHub Pages.
 *
 * `handleCodeInApp` stays `false`: the flow is completed by the hosted Firebase
 * page and redirected back to this URL, so no custom handler is needed.
 */
export function buildActionCodeSettings(origin: string, basePath: string): ActionCodeSettings {
  const normalizedOrigin = origin.trim().replace(/\/+$/, '');
  return {
    url: `${normalizedOrigin}${normalizeBasePath(basePath)}/`,
    handleCodeInApp: false,
  };
}

/**
 * Last-resort settings used when Firebase rejects the configured continue URL
 * (`invalid-continue-uri` / `unauthorized-continue-uri`).
 *
 * The origin root is always part of the deployment and is the minimum URL the
 * project can authorize, so a single retry with it still delivers the e-mail.
 */
export function buildFallbackActionCodeSettings(origin: string): ActionCodeSettings {
  return {
    url: `${origin.trim().replace(/\/+$/, '')}/`,
    handleCodeInApp: false,
  };
}

/** Codes that mean "this redirect URL is not acceptable" (retry once). */
export function isContinueUriRejection(code: string | null): boolean {
  return code === 'auth/invalid-continue-uri' || code === 'auth/unauthorized-continue-uri';
}
