/**
 * Runtime configuration contract shared by the shell and the API client.
 *
 * The values are injected by `public/config.js` (generated at deploy time by
 * `scripts/write-config.mjs`) so a single production build can target several
 * environments.
 */

export interface RawAppConfig {
  apiBaseUrl?: string;
  basePath?: string;
}

export interface AppConfig {
  /** Absolute API origin (no trailing slash) or an empty string. */
  readonly apiBaseUrl: string;
  /** Deploy sub-path, normalized without a trailing slash, or an empty string. */
  readonly basePath: string;
  /** True when production runs without an API origin configured. */
  readonly apiUnavailable: boolean;
}

declare global {
  interface Window {
    DevPilotConfig?: RawAppConfig;
  }
}

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
const LOCAL_API_FALLBACK = 'http://localhost:8000';

export function trimTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '');
}

export function normalizeBasePath(value: string | undefined): string {
  const trimmed = (value ?? '').trim();
  if (trimmed === '' || trimmed === '/') {
    return '';
  }
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  return trimTrailingSlashes(withLeadingSlash);
}

function isLoopback(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

/**
 * Reads `window.DevPilotConfig` and applies the documented fallbacks:
 * a loopback hostname defaults to the local API, while a production build with
 * no configured origin is flagged as unavailable instead of issuing requests
 * to its own static origin.
 */
export function readRuntimeConfig(win: Window | undefined = globalThis.window): AppConfig {
  const raw = win?.DevPilotConfig ?? {};
  const configured = trimTrailingSlashes((raw.apiBaseUrl ?? '').trim());
  const basePath = normalizeBasePath(raw.basePath);

  if (configured !== '') {
    return { apiBaseUrl: configured, basePath, apiUnavailable: false };
  }

  const hostname = win?.location?.hostname ?? '';
  if (hostname !== '' && isLoopback(hostname)) {
    return { apiBaseUrl: LOCAL_API_FALLBACK, basePath, apiUnavailable: false };
  }

  return { apiBaseUrl: '', basePath, apiUnavailable: true };
}
