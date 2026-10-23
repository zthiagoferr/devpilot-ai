import { Injectable, inject } from '@angular/core';

import { AUTH_TOKEN_PROVIDER } from '../auth/auth-token.provider';
import { ConfigService } from '../config/config.service';
import {
  mapErrorResponse,
  mapInvalidResponseError,
  mapNetworkError,
  mapUnavailableError,
} from './api-error.mapper';
import { Analysis, CreateAnalysisRequest, OrchestratorStatus } from './api.types';

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

  private async request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    if (!this.config.hasApi()) {
      throw mapUnavailableError();
    }

    const headers = new Headers({ Accept: 'application/json' });
    if (body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }

    const token = this.authToken();
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
      const payload = await this.readBody(response);
      throw mapErrorResponse(response.status, payload, response.headers.get('Retry-After'));
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const payload = await this.readBody(response);
    if (payload === null) {
      throw mapInvalidResponseError();
    }
    return payload as T;
  }

  private async readBody(response: Response): Promise<unknown> {
    const text = await response.text();
    if (text.trim() === '') {
      return null;
    }
    try {
      return JSON.parse(text) as unknown;
    } catch (error) {
      if (!response.ok) {
        // Non-JSON error bodies (proxy HTML, gateway timeouts) still produce a
        // readable message through the status-specific mapper.
        return text;
      }
      throw mapInvalidResponseError(error);
    }
  }
}
