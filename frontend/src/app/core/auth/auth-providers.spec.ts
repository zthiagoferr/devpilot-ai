import { describe, expect, it } from 'vitest';

import {
  AUTH_PROVIDERS,
  enabledAuthProviders,
  findAuthProvider,
  providerLabelForMethod,
} from './auth-providers';
import { createFakeFirebaseAuth, type FakeOAuthProvider } from './testing/fake-firebase-auth';

describe('AUTH_PROVIDERS', () => {
  it('exposes the four OAuth providers in the documented order', () => {
    expect(AUTH_PROVIDERS.map((provider) => provider.id)).toEqual([
      'github',
      'google',
      'apple',
      'microsoft',
    ]);
    expect(AUTH_PROVIDERS.map((provider) => provider.label)).toEqual([
      'GitHub',
      'Google',
      'Apple',
      'Microsoft',
    ]);
  });

  it('resolves a definition by id and returns null for unknown ids', () => {
    expect(findAuthProvider('github')?.label).toBe('GitHub');
    expect(findAuthProvider('unknown' as 'github')).toBeNull();
  });

  it('builds provider objects with the expected custom parameters', () => {
    const { bundle } = createFakeFirebaseAuth();
    const github = findAuthProvider('github')?.create(bundle.auth) as unknown as FakeOAuthProvider;
    const google = findAuthProvider('google')?.create(bundle.auth) as unknown as FakeOAuthProvider;
    const apple = findAuthProvider('apple')?.create(bundle.auth) as unknown as FakeOAuthProvider;
    const microsoft = findAuthProvider('microsoft')?.create(
      bundle.auth,
    ) as unknown as FakeOAuthProvider;

    expect(github.providerId).toBe('github.com');
    expect(github.customParameters).toBeNull();

    expect(google.providerId).toBe('google.com');
    expect(google.customParameters).toEqual({ prompt: 'select_account' });

    expect(apple.providerId).toBe('apple.com');
    expect(apple.scopes).toEqual(['email', 'name']);

    expect(microsoft.providerId).toBe('microsoft.com');
    expect(microsoft.customParameters).toEqual({ tenant: 'common' });
  });

  it('enables every provider when the allow-list is absent or empty', () => {
    expect(enabledAuthProviders(undefined).map((provider) => provider.id)).toEqual([
      'github',
      'google',
      'apple',
      'microsoft',
    ]);
    expect(enabledAuthProviders([]).map((provider) => provider.id)).toEqual([
      'github',
      'google',
      'apple',
      'microsoft',
    ]);
  });

  it('filters providers by the configured allow-list', () => {
    expect(enabledAuthProviders(['google', 'apple']).map((provider) => provider.id)).toEqual([
      'google',
      'apple',
    ]);
    expect(findAuthProvider('github')?.enabled?.(['google'])).toBe(false);
    expect(findAuthProvider('github')?.enabled?.(['github'])).toBe(true);
  });
});

describe('providerLabelForMethod', () => {
  it.each([
    ['password', 'e-mail e senha'],
    ['github.com', 'GitHub'],
    ['google.com', 'Google'],
    ['apple.com', 'Apple'],
    ['microsoft.com', 'Microsoft'],
  ])('maps %s to %s', (method, expected) => {
    expect(providerLabelForMethod(method)).toBe(expected);
  });

  it('keeps an unknown method as-is', () => {
    expect(providerLabelForMethod('custom.method')).toBe('custom.method');
  });
});
