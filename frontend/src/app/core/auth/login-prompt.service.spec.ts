import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  LOGIN_AUTH_ERROR_MESSAGE,
  LOGIN_INITIALIZING_MESSAGE,
  LOGIN_UNAVAILABLE_MESSAGE,
} from './auth-errors';
import { AuthService } from './auth.service';
import { AuthStatus } from './auth.types';
import { LoginPromptService } from './login-prompt.service';

describe('LoginPromptService', () => {
  async function create(
    configured: boolean,
    status: AuthStatus = configured ? 'ready' : 'unconfigured',
  ): Promise<LoginPromptService> {
    TestBed.resetTestingModule();
    const statusSignal = signal<AuthStatus>(status);
    await TestBed.configureTestingModule({
      providers: [
        {
          provide: AuthService,
          useValue: {
            get configured() {
              return configured;
            },
            get isAuthConfigured() {
              return configured;
            },
            get loginAvailable() {
              return () => configured && statusSignal() === 'ready';
            },
            status: statusSignal,
          },
        },
      ],
    }).compileComponents();
    return TestBed.inject(LoginPromptService);
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('does not open the Firebase flow when authentication is not configured', async () => {
    const prompts = await create(false);

    expect(prompts.open()).toBe(false);
    expect(prompts.isOpen()).toBe(false);
    expect(prompts.notice()).toBe(LOGIN_UNAVAILABLE_MESSAGE);
  });

  it('opens the flow and clears an old notice when authentication is configured', async () => {
    const prompts = await create(true, 'ready');

    expect(prompts.open({ mode: 'register', message: 'Crie sua conta.' })).toBe(true);
    expect(prompts.isOpen()).toBe(true);
    expect(prompts.mode()).toBe('register');
    expect(prompts.message()).toBe('Crie sua conta.');
    expect(prompts.notice()).toBe('');
  });

  it('keeps the dialog closed when the configured SDK failed to bootstrap', async () => {
    const prompts = await create(true, 'error');

    expect(prompts.open()).toBe(false);
    expect(prompts.isOpen()).toBe(false);
    expect(prompts.notice()).toBe(LOGIN_AUTH_ERROR_MESSAGE);
  });

  it('does not open a dead form while the SDK is still loading', async () => {
    const prompts = await create(true, 'loading');

    expect(prompts.open()).toBe(false);
    expect(prompts.isOpen()).toBe(false);
    expect(prompts.notice()).toBe(LOGIN_INITIALIZING_MESSAGE);
  });

  it('exposes a dismissible notice', async () => {
    const prompts = await create(false);

    prompts.open();
    expect(prompts.notice()).not.toBe('');
    prompts.clearNotice();
    expect(prompts.notice()).toBe('');
  });
});
