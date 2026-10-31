import type { AuthProvider } from 'firebase/auth';

import type { IconName } from '../../shared/components/icon/icon.component';
import type { FirebaseAuthSdk } from './firebase-auth-loader';

/** OAuth providers supported by the login dialog. */
export type OAuthProviderId = 'github' | 'google' | 'apple' | 'microsoft';

export interface AuthProviderDefinition {
  readonly id: OAuthProviderId;
  /** pt-BR label used on buttons and in messages. */
  readonly label: string;
  readonly icon: IconName;
  /** Builds the SDK provider object for a popup/redirect flow. */
  readonly create: (sdk: FirebaseAuthSdk) => AuthProvider;
  /**
   * Optional allow-list predicate. The argument is the deployment's
   * `firebase.providers` value; absent/empty means the provider is enabled.
   */
  readonly enabled?: (providers: readonly string[] | undefined) => boolean;
}

function listed(id: OAuthProviderId): (providers: readonly string[] | undefined) => boolean {
  return (providers) => providers === undefined || providers.length === 0 || providers.includes(id);
}

/**
 * Ordered registry of the OAuth providers offered in the login dialog.
 *
 * Every definition keeps the SDK call inside `create`, so the dialog and the
 * service never instantiate a provider themselves (and tests can inspect the
 * resulting object through the fake SDK).
 */
export const AUTH_PROVIDERS: readonly AuthProviderDefinition[] = [
  {
    id: 'github',
    label: 'GitHub',
    icon: 'gitBranch',
    create: (sdk) => new sdk.GithubAuthProvider(),
    enabled: listed('github'),
  },
  {
    id: 'google',
    label: 'Google',
    icon: 'google',
    create: (sdk) => new sdk.GoogleAuthProvider().setCustomParameters({ prompt: 'select_account' }),
    enabled: listed('google'),
  },
  {
    id: 'apple',
    label: 'Apple',
    icon: 'apple',
    create: (sdk) => {
      const provider = new sdk.OAuthProvider('apple.com');
      provider.addScope('email');
      provider.addScope('name');
      return provider;
    },
    enabled: listed('apple'),
  },
  {
    id: 'microsoft',
    label: 'Microsoft',
    icon: 'microsoft',
    create: (sdk) =>
      new sdk.OAuthProvider('microsoft.com').setCustomParameters({ tenant: 'common' }),
    enabled: listed('microsoft'),
  },
];

export function findAuthProvider(id: OAuthProviderId): AuthProviderDefinition | null {
  return AUTH_PROVIDERS.find((provider) => provider.id === id) ?? null;
}

/** Enabled definitions for a deployment's provider allow-list. */
export function enabledAuthProviders(
  providers: readonly string[] | undefined,
): readonly AuthProviderDefinition[] {
  return AUTH_PROVIDERS.filter((provider) => provider.enabled?.(providers) ?? true);
}

/**
 * Human label for a Firebase sign-in method (as returned by
 * `fetchSignInMethodsForEmail` / `account-exists-with-different-credential`).
 */
export function providerLabelForMethod(method: string): string {
  switch (method) {
    case 'password':
      return 'e-mail e senha';
    case 'github.com':
      return 'GitHub';
    case 'google.com':
      return 'Google';
    case 'apple.com':
      return 'Apple';
    case 'microsoft.com':
      return 'Microsoft';
    default:
      return method;
  }
}
