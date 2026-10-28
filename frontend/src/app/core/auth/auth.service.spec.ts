import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { ConfigService } from '../config/config.service';
import { AuthService } from './auth.service';

describe('AuthService.loginAvailable', () => {
  function create(firebase: Record<string, string>): AuthService {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [AuthService, { provide: ConfigService, useValue: { firebase } }],
    });
    return TestBed.inject(AuthService);
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('stays unavailable before the bootstrap reaches the ready state', () => {
    const auth = create({ apiKey: 'public-key', projectId: 'project' });

    expect(auth.isAuthConfigured).toBe(true);
    expect(auth.status()).toBe('idle');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('loading');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('error');
    expect(auth.loginAvailable()).toBe(false);

    auth.status.set('ready');
    expect(auth.loginAvailable()).toBe(true);
  });

  it('is unavailable when the deployment carries no public configuration', () => {
    const auth = create({ apiKey: '', projectId: '' });

    expect(auth.isAuthConfigured).toBe(false);
    expect(auth.status()).toBe('unconfigured');
    expect(auth.loginAvailable()).toBe(false);
  });
});
