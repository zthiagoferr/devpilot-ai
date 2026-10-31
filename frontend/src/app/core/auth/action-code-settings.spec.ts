import { describe, expect, it } from 'vitest';

import {
  buildActionCodeSettings,
  buildFallbackActionCodeSettings,
  isContinueUriRejection,
} from './action-code-settings';

describe('action code settings', () => {
  it('builds the continue URL from the origin and the normalized sub-path', () => {
    expect(buildActionCodeSettings('https://zthiagoferr.github.io', '/devpilot-ai')).toEqual({
      url: 'https://zthiagoferr.github.io/devpilot-ai/',
      handleCodeInApp: false,
    });
    expect(buildActionCodeSettings('https://zthiagoferr.github.io/', 'devpilot-ai/')).toEqual({
      url: 'https://zthiagoferr.github.io/devpilot-ai/',
      handleCodeInApp: false,
    });
  });

  it('keeps the origin root when the deployment has no sub-path', () => {
    expect(buildActionCodeSettings('http://localhost:4200', '')).toEqual({
      url: 'http://localhost:4200/',
      handleCodeInApp: false,
    });
    expect(buildActionCodeSettings('http://localhost:4200', '/')).toEqual({
      url: 'http://localhost:4200/',
      handleCodeInApp: false,
    });
  });

  it('falls back to the origin root', () => {
    expect(buildFallbackActionCodeSettings('https://zthiagoferr.github.io')).toEqual({
      url: 'https://zthiagoferr.github.io/',
      handleCodeInApp: false,
    });
    expect(buildFallbackActionCodeSettings('https://zthiagoferr.github.io/')).toEqual({
      url: 'https://zthiagoferr.github.io/',
      handleCodeInApp: false,
    });
  });

  it('only retries for the continue-URL rejection codes', () => {
    expect(isContinueUriRejection('auth/invalid-continue-uri')).toBe(true);
    expect(isContinueUriRejection('auth/unauthorized-continue-uri')).toBe(true);
    expect(isContinueUriRejection('auth/too-many-requests')).toBe(false);
    expect(isContinueUriRejection(null)).toBe(false);
  });
});
