import { describe, expect, it } from 'vitest';

import {
  ApiError,
  isApiError,
  mapErrorResponse,
  mapNetworkError,
  parseRetryAfter,
} from './api-error.mapper';

describe('api error mapper', () => {
  it('maps a string detail for 413 without losing the server message', () => {
    const error = mapErrorResponse(413, { detail: 'Source code is too large (2000000 bytes).' });

    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe('payload-too-large');
    expect(error.status).toBe(413);
    expect(error.message).toBe('Source code is too large (2000000 bytes).');
  });

  it('maps a Pydantic detail array to field errors and a readable message', () => {
    const error = mapErrorResponse(422, {
      detail: [
        { loc: ['body', 'project_name'], msg: 'Field required', type: 'missing' },
        {
          loc: ['body', 'source_code'],
          msg: 'String should have at least 1 character',
          type: 'string_too_short',
        },
      ],
    });

    expect(error.kind).toBe('validation');
    expect(error.fieldErrors).toEqual({
      project_name: 'Field required',
      source_code: 'String should have at least 1 character',
    });
    expect(error.message).toContain('Field required');
    expect(error.message).toContain('String should have at least 1 character');
    expect(error.message).not.toContain('[object Object]');
  });

  it('never renders an object detail as [object Object]', () => {
    const error = mapErrorResponse(400, { detail: { msg: 'Invalid task', code: 'task' } });

    expect(error.message).toContain('Invalid task');
    expect(error.message).not.toContain('[object Object]');
  });

  it('uses Retry-After seconds on 429 responses', () => {
    const error = mapErrorResponse(429, { detail: 'Too many requests' }, '12');

    expect(error.kind).toBe('rate-limited');
    expect(error.retryAfterSeconds).toBe(12);
    expect(error.message).toContain('12 s');
  });

  it('parses an HTTP-date Retry-After header', () => {
    const future = new Date(Date.now() + 30_000).toUTCString();
    const seconds = parseRetryAfter(future);

    expect(seconds).not.toBeNull();
    expect(seconds).toBeGreaterThan(0);
    expect(seconds).toBeLessThanOrEqual(30);
  });

  it('maps network failures with a recovery-oriented message', () => {
    const error = mapNetworkError(new TypeError('Failed to fetch'));

    expect(error.kind).toBe('network');
    expect(error.status).toBeNull();
    expect(error.message).toContain('Não foi possível falar com a API');
    expect(isApiError(error)).toBe(true);
  });

  it('ignores malformed Retry-After values and keeps a generic 429 message', () => {
    expect(parseRetryAfter('not-a-date')).toBeNull();
    const error = mapErrorResponse(429, null, 'not-a-date');

    expect(error.retryAfterSeconds).toBeNull();
    expect(error.message).toContain('Muitas solicitações');
  });
});
