import { describe, expect, it } from 'vitest';

import { FIREBASE_CONFIG, isFirebaseConfigured, resolveFirebaseConfig } from './firebase-config';

describe('Firebase runtime config', () => {
  it('uses the public project configuration by default', () => {
    expect(resolveFirebaseConfig()).toEqual(FIREBASE_CONFIG);
    expect(resolveFirebaseConfig({})).toEqual(FIREBASE_CONFIG);
    expect(isFirebaseConfigured(FIREBASE_CONFIG)).toBe(true);
  });

  it('merges a partial window.DevPilotConfig.firebase override', () => {
    const resolved = resolveFirebaseConfig({ apiKey: 'override-key' });

    expect(resolved.apiKey).toBe('override-key');
    expect(resolved.projectId).toBe(FIREBASE_CONFIG.projectId);
  });

  it('flags an explicitly empty configuration as unavailable', () => {
    const resolved = resolveFirebaseConfig({ apiKey: '', projectId: '' });

    expect(isFirebaseConfigured(resolved)).toBe(false);
  });
});
