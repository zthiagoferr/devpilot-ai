import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_TOKEN_PROVIDER, AuthTokenProvider } from '../auth/auth-token.provider';
import { ConfigService } from '../config/config.service';
import { ApiClient, filenameFromDisposition } from './api-client';

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

  it('forwards an explicit language filter to /repositories/load', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ files: [], truncated: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const api = setup(async () => null);
    await api.loadRepository('owner/repo', '', undefined, 'advpl');

    const init = fetchMock.mock.calls[0]?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({
      repository_url: 'owner/repo',
      language: 'advpl',
    });
  });

  it('creates a correction with the issue reference and optional context', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(CORRECTION), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const api = setup(async () => 'token-123');
    const result = await api.createCorrection({
      analysis_id: 'analysis-1',
      file: 'src/app.prg',
      language: 'advpl',
      source_code: 'User Function X()\nReturn\n',
      issue: { message: 'Bloco', severity: 'high', line: 2, code: 'unclosed_block' },
      protheus_version: '12.1.2410',
    });

    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('http://api.test/corrections');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      analysis_id: 'analysis-1',
      file: 'src/app.prg',
      language: 'advpl',
      source_code: 'User Function X()\nReturn\n',
      issue: { message: 'Bloco', severity: 'high', line: 2, code: 'unclosed_block' },
      protheus_version: '12.1.2410',
    });
    expect(result.corrected_code).toContain('Return');
  });

  it('lists, reads and decides corrections with the bearer token', async () => {
    fetchMock.mockImplementation(
      async () =>
        new Response(JSON.stringify([CORRECTION]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    const api = setup(async () => 'token-123');

    await api.listCorrections('analysis-1');
    await api.getCorrection('corr-1');
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...CORRECTION, status: 'approved' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    await api.decideCorrection('corr-1', { status: 'approved' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://api.test/corrections?analysis_id=analysis-1');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('http://api.test/corrections/corr-1');
    expect(fetchMock.mock.calls[2]?.[0]).toBe('http://api.test/corrections/corr-1/decision');
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({
      status: 'approved',
    });
    for (const call of fetchMock.mock.calls) {
      const headers = call[1]?.headers as Headers;
      expect(headers.get('Authorization')).toBe('Bearer token-123');
    }
  });

  it('downloads a correction as a Blob and reads the filename from the header', async () => {
    fetchMock.mockResolvedValue(
      new Response('User Function X()\nReturn\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Content-Disposition': 'attachment; filename="financeiro.corrected.prg"',
        },
      }),
    );
    const api = setup(async () => 'token-123');

    const result = await api.exportCorrection('corr-1', 'corrected');

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://api.test/corrections/corr-1/export?format=corrected',
    );
    expect(result.filename).toBe('financeiro.corrected.prg');
    expect(result.contentType).toContain('text/plain');
    expect(result.blob.size).toBeGreaterThan(0);
  });

  it('marks a non-JSON proxy error body as unexpected', async () => {
    fetchMock.mockResolvedValue(
      new Response('<html><body>Service suspended</body></html>', {
        status: 503,
        headers: { 'Content-Type': 'text/html' },
      }),
    );
    const api = setup(async () => null);

    await expect(api.getOrchestratorStatus()).rejects.toMatchObject({
      status: 503,
      bodyIsJson: false,
      message: 'A análise falhou no servidor. Tente novamente em instantes.',
    });
  });

  it('maps an unavailable correction (503) without hiding the status', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'AI correction is not configured.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const api = setup(async () => null);

    await expect(
      api.createCorrection({
        source_code: 'print(1)',
        issue: { message: 'x', severity: 'low' },
      }),
    ).rejects.toMatchObject({ status: 503, kind: 'server' });
  });
});

describe('filenameFromDisposition', () => {
  it('reads quoted, unquoted and UTF-8 filenames', () => {
    expect(filenameFromDisposition('attachment; filename="app.py"')).toBe('app.py');
    expect(filenameFromDisposition('attachment; filename=app.py')).toBe('app.py');
    expect(filenameFromDisposition("attachment; filename*=UTF-8''relat%C3%B3rio.txt")).toBe(
      'relatório.txt',
    );
    expect(filenameFromDisposition(null)).toBeNull();
    expect(filenameFromDisposition('attachment')).toBeNull();
  });
});

const CORRECTION = {
  id: 'corr-1',
  analysis_id: 'analysis-1',
  language: 'advpl',
  file: 'src/app.prg',
  issue_ref: 'Bloco',
  original_code: 'User Function X()\nReturn\n',
  corrected_code: 'User Function X()\nReturn\n',
  diff: '--- a/src/app.prg\n+++ b/src/app.prg\n@@ -1 +1 @@\n-User Function X()\n+User Function Y()\n',
  explanation: 'Ajuste do bloco.',
  origin: 'ai',
  post_validation: { status: 'passed', target_resolved: true, issues: [], summary: '' },
  status: 'pending',
  model: 'fake',
  protheus_version: '12.1.2410',
  created_at: '2026-10-28T12:00:00Z',
  decided_at: null,
};
