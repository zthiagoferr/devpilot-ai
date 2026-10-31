import { Injectable, inject } from '@angular/core';

import { AUTH_TOKEN_PROVIDER } from '../auth/auth-token.provider';
import { ConfigService } from '../config/config.service';
import {
  mapErrorResponse,
  mapInvalidResponseError,
  mapNetworkError,
  mapUnavailableError,
} from './api-error.mapper';
import {
  Analysis,
  AnalysisLanguage,
  Correction,
  CorrectionBatchCreate,
  CorrectionBatchResponse,
  CorrectionCreate,
  CorrectionDecision,
  CorrectionExport,
  CorrectionExportFormat,
  CreateAnalysisRequest,
  OrchestratorStatus,
  RepositoryLoad,
  RepositoryLoadRequest,
} from './api.types';

type HttpMethod = 'GET' | 'POST';

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (typeof error === 'object' &&
      error !== null &&
      'name' in error &&
      (error as { name?: unknown }).name === 'AbortError')
  );
}

/**
 * Thin typed wrapper over `fetch`.
 *
 * A single place owns the base URL, the bearer-token extension point and the
 * translation of every failure mode into an `ApiError`.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly config = inject(ConfigService);
  private readonly authToken = inject(AUTH_TOKEN_PROVIDER);

  getOrchestratorStatus(signal?: AbortSignal): Promise<OrchestratorStatus> {
    return this.request<OrchestratorStatus>('GET', '/agents/orchestrator', undefined, signal);
  }

  createAnalysis(payload: CreateAnalysisRequest, signal?: AbortSignal): Promise<Analysis> {
    return this.request<Analysis>('POST', '/analyses', payload, signal);
  }

  getAnalysis(id: string, signal?: AbortSignal): Promise<Analysis> {
    return this.request<Analysis>('GET', `/analyses/${encodeURIComponent(id)}`, undefined, signal);
  }

  listAnalyses(limit = 20, signal?: AbortSignal): Promise<Analysis[]> {
    return this.request<Analysis[]>('GET', `/analyses?limit=${limit}`, undefined, signal);
  }

  /**
   * Loads the analyzable files of a public repository.
   *
   * `language` is an optional filter forwarded to the backend; `auto` (and an
   * empty value) keeps the multi-language discovery.
   */
  loadRepository(
    repositoryUrl: string,
    branch?: string | null,
    signal?: AbortSignal,
    language?: AnalysisLanguage | null,
  ): Promise<RepositoryLoad> {
    const payload: RepositoryLoadRequest = {
      repository_url: repositoryUrl,
      ...(branch ? { branch } : {}),
      ...(language && language !== 'auto' ? { language } : {}),
    };
    return this.request<RepositoryLoad>('POST', '/repositories/load', payload, signal);
  }

  createCorrection(payload: CorrectionCreate, signal?: AbortSignal): Promise<Correction> {
    return this.request<Correction>('POST', '/corrections', payload, signal);
  }

  /**
   * Requests AI corrections for up to three files in one synchronous call.
   *
   * Each completed file is persisted individually by the backend, so approval
   * stays per file through `decideCorrection`.
   */
  createCorrectionBatch(
    payload: CorrectionBatchCreate,
    signal?: AbortSignal,
  ): Promise<CorrectionBatchResponse> {
    return this.request<CorrectionBatchResponse>('POST', '/corrections/batch', payload, signal);
  }

  listCorrections(analysisId: string, signal?: AbortSignal): Promise<Correction[]> {
    return this.request<Correction[]>(
      'GET',
      `/corrections?analysis_id=${encodeURIComponent(analysisId)}`,
      undefined,
      signal,
    );
  }

  getCorrection(id: string, signal?: AbortSignal): Promise<Correction> {
    return this.request<Correction>(
      'GET',
      `/corrections/${encodeURIComponent(id)}`,
      undefined,
      signal,
    );
  }

  decideCorrection(
    id: string,
    decision: CorrectionDecision,
    signal?: AbortSignal,
  ): Promise<Correction> {
    return this.request<Correction>(
      'POST',
      `/corrections/${encodeURIComponent(id)}/decision`,
      decision,
      signal,
    );
  }

  /**
   * Downloads one correction as a `Blob`.
   *
   * The endpoint requires the caller's bearer token, so it cannot be a plain
   * anchor `href`; the authenticated `fetch` goes through the same error
   * mapping as every other call.
   */
  async exportCorrection(
    id: string,
    format: CorrectionExportFormat = 'corrected',
    signal?: AbortSignal,
  ): Promise<CorrectionExport> {
    const response = await this.send(
      'GET',
      `/corrections/${encodeURIComponent(id)}/export?format=${format}`,
      undefined,
      signal,
    );

    return {
      blob: await response.blob(),
      filename: filenameFromDisposition(response.headers.get('Content-Disposition')),
      contentType: response.headers.get('Content-Type'),
    };
  }

  private async request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await this.send(method, path, body, signal);

    if (response.status === 204) {
      return undefined as T;
    }

    const { value, isJson } = await this.readBody(response);
    if (value === null || !isJson) {
      throw mapInvalidResponseError();
    }
    return value as T;
  }

  private async send(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<Response> {
    if (!this.config.hasApi()) {
      throw mapUnavailableError();
    }

    const headers = new Headers({ Accept: 'application/json' });
    if (body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }

    const token = await this.authToken();
    if (token !== null && token !== '') {
      headers.set('Authorization', `Bearer ${token}`);
    }

    let response: Response;
    try {
      response = await fetch(`${this.config.apiBaseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
        cache: 'no-store',
      });
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }
      throw mapNetworkError(error);
    }

    if (!response.ok) {
      const { value, isJson } = await this.readBody(response);
      throw mapErrorResponse(
        response.status,
        value,
        response.headers.get('Retry-After'),
        isJson,
      );
    }

    return response;
  }

  private async readBody(response: Response): Promise<{ value: unknown; isJson: boolean }> {
    const text = await response.text();
    if (text.trim() === '') {
      return { value: null, isJson: true };
    }
    try {
      return { value: JSON.parse(text) as unknown, isJson: true };
    } catch (error) {
      if (!response.ok) {
        // Non-JSON error bodies (proxy HTML, gateway timeouts) still produce a
        // readable message through the status-specific mapper; the raw body is
        // preserved only so the mapper can mark it as unexpected.
        return { value: text, isJson: false };
      }
      throw mapInvalidResponseError(error);
    }
  }
}

/** Extracts the filename from a server `Content-Disposition` header. */
export function filenameFromDisposition(header: string | null): string | null {
  if (header === null || header.trim() === '') {
    return null;
  }

  const utf8 = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (utf8?.[1] !== undefined) {
    try {
      return decodeURIComponent(utf8[1].trim().replace(/^"|"$/g, ''));
    } catch {
      return utf8[1].trim().replace(/^"|"$/g, '');
    }
  }

  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() ?? null;
}
