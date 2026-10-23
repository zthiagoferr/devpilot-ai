import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_TOKEN_PROVIDER, AuthTokenProvider } from '../auth/auth-token.provider';
import { ConfigService } from '../config/config.service';
import { ApiClient } from './api-client';

describe('ApiClient', () => {
  const fetchMock = vi.fn();

  function setup(token: AuthTokenProvider): ApiClient {
    TestBed.configureTestingModule({
      providers: [
        {
          provide: ConfigService,
          useValue: { apiBaseUrl: 'http://api.test', hasApi: () => true },
        },
        { provide: AUTH_TOKEN_PROVIDER, useValue: token },
      ],
    });
    return TestBed.inject(ApiClient);
  }

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('attaches the bearer token resolved by the provider', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const api = setup(async () => 'token-123');
    await api.listAnalyses();

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get('Authorization')).toBe('Bearer token-123');
  });

  it('omits Authorization for a visitor', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const api = setup(async () => null);
    await api.listAnalyses();

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.has('Authorization')).toBe(false);
  });

  it('maps a 401 to an unauthorized ApiError', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Authentication required.' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const api = setup(async () => 'expired');

    await expect(api.listAnalyses()).rejects.toMatchObject({
      kind: 'unauthorized',
      status: 401,
    });
  });

  it('posts the repository reference and optional branch to /repositories/load', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          files: [{ path: 'src/app.py', size: 10, source_code: 'print(1)' }],
          truncated: true,
          message: null,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const api = setup(async () => null);
    const result = await api.loadRepository('owner/repo', 'main');

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('http://api.test/repositories/load');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      repository_url: 'owner/repo',
      branch: 'main',
    });
    expect(result.files[0]?.path).toBe('src/app.py');
    expect(result.truncated).toBe(true);
  });
});
