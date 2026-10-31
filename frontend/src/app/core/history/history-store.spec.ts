import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '../api/api-client';
import { ApiError } from '../api/api-error.mapper';
import { Analysis, AnalysisResult } from '../api/api.types';
import { AuthService } from '../auth/auth.service';
import { LoginPromptService } from '../auth/login-prompt.service';
import { HistoryStore } from './history-store';

function analysis(
  id: string,
  createdAt: string,
  score: number | null | undefined,
  project = `projeto-${id}`,
  details: Partial<AnalysisResult> = {},
): Analysis {
  return {
    id,
    task: 'code',
    project_name: project,
    source_code: 'print(1)',
    repository_url: null,
    result: score === undefined ? null : { score, ...details },
    status: 'completed',
    created_at: createdAt,
  };
}

describe('HistoryStore', () => {
  const listAnalyses = vi.fn();
  const expireSession = vi.fn();
  const openPrompt = vi.fn();
  const authenticated = signal(true);

  function setup(): HistoryStore {
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiClient, useValue: { listAnalyses } },
        {
          provide: AuthService,
          useValue: {
            isAuthenticated: authenticated.asReadonly(),
            expireSession,
          },
        },
        { provide: LoginPromptService, useValue: { open: openPrompt } },
      ],
    });
    return TestBed.inject(HistoryStore);
  }

  beforeEach(() => {
    listAnalyses.mockReset();
    expireSession.mockReset();
    openPrompt.mockReset();
    authenticated.set(true);
  });

  it('sorts newest first and computes the average without NaN', async () => {
    listAnalyses.mockResolvedValue([
      analysis('old', '2026-01-01T10:00:00Z', 70),
      analysis('newest', '2026-03-01T10:00:00Z', 90),
      analysis('missing', '2026-02-01T10:00:00Z', null),
      analysis('invalid', '2026-02-15T10:00:00Z', Number.NaN),
      analysis('no-result', '2026-01-15T10:00:00Z', undefined),
    ]);

    const store = setup();
    await store.load();

    expect(store.sorted().map((item) => item.id)).toEqual([
      'newest',
      'invalid',
      'missing',
      'no-result',
      'old',
    ]);
    expect(store.total()).toBe(5);
    expect(store.averageScore()).toBe(80);
    expect(store.latest()?.id).toBe('newest');
    expect(store.recent()).toHaveLength(5);
  });

  it('returns null for the average when no analysis has a finite score', async () => {
    listAnalyses.mockResolvedValue([
      analysis('a', '2026-01-01T10:00:00Z', null),
      analysis('b', '2026-01-02T10:00:00Z', undefined),
    ]);

    const store = setup();
    await store.load();

    expect(store.averageScore()).toBeNull();
  });

  it('excludes skipped and unavailable scores from the average', async () => {
    listAnalyses.mockResolvedValue([
      analysis('evaluated', '2026-01-01T10:00:00Z', 80, 'avaliada', {
        score_status: 'evaluated',
      }),
      // Unknown language: the neutral 100 is not an evaluation.
      analysis('skipped', '2026-01-02T10:00:00Z', 100, 'ignorada', {
        score_status: 'skipped',
        validation_skipped: true,
      }),
      // Validator failure: the 90 reflects the error, not the code.
      analysis('unavailable', '2026-01-03T10:00:00Z', 90, 'indisponivel', {
        score_status: 'unavailable',
      }),
    ]);

    const store = setup();
    await store.load();

    expect(store.averageScore()).toBe(80);
  });

  it('keeps the legacy validation_skipped flag out of the average', async () => {
    listAnalyses.mockResolvedValue([
      analysis('evaluated', '2026-01-01T10:00:00Z', 70),
      analysis('legacy-skipped', '2026-01-02T10:00:00Z', 100, 'legado', {
        validation_skipped: true,
      }),
    ]);

    const store = setup();
    await store.load();

    expect(store.averageScore()).toBe(70);
  });

  it('returns null when every analysis was skipped or unavailable', async () => {
    listAnalyses.mockResolvedValue([
      analysis('skipped', '2026-01-01T10:00:00Z', 100, 'ignorada', {
        score_status: 'skipped',
      }),
      analysis('unavailable', '2026-01-02T10:00:00Z', 90, 'indisponivel', {
        score_status: 'unavailable',
      }),
    ]);

    const store = setup();
    await store.load();

    expect(store.averageScore()).toBeNull();
  });

  it('marks an empty history without turning it into an error', async () => {
    listAnalyses.mockResolvedValue([]);

    const store = setup();
    await store.load();

    expect(store.state()).toBe('empty');
    expect(store.total()).toBe(0);
    expect(store.averageScore()).toBeNull();
  });

  it('never calls the authenticated endpoint for a visitor', async () => {
    authenticated.set(false);
    const store = setup();

    await store.load();

    expect(listAnalyses).not.toHaveBeenCalled();
    expect(store.state()).toBe('unauthorized');
    expect(openPrompt).not.toHaveBeenCalled();
  });

  it('opens the login dialog when the API rejects the session with 401', async () => {
    listAnalyses.mockRejectedValue(new ApiError('unauthorized', 'Authentication required.'));

    const store = setup();
    await store.load();

    expect(store.state()).toBe('unauthorized');
    expect(expireSession).toHaveBeenCalledOnce();
    expect(openPrompt).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'login', message: expect.stringContaining('expirou') }),
    );
  });

  it('keeps a non-auth failure as an error with the mapped message', async () => {
    listAnalyses.mockRejectedValue(new ApiError('network', 'Sem conexão com a API.'));

    const store = setup();
    await store.load();

    expect(store.state()).toBe('error');
    expect(store.error()).toBe('Sem conexão com a API.');
    expect(openPrompt).not.toHaveBeenCalled();
  });
});
