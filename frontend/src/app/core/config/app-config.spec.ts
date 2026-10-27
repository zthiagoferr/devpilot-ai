import { describe, expect, it } from 'vitest';

import { normalizeBasePath, RawAppConfig, readRuntimeConfig } from './app-config';

function fakeWindow(hostname: string, config?: RawAppConfig): Window {
  return {
    location: { hostname },
    DevPilotConfig: config,
  } as unknown as Window;
}

describe('readRuntimeConfig', () => {
  it('uses and normalizes an explicitly configured API origin', () => {
    const config = readRuntimeConfig(
      fakeWindow('devpilot.example.com', {
        apiBaseUrl: 'https://api.example.com/',
        basePath: '/devpilot/',
      }),
    );

    expect(config.apiBaseUrl).toBe('https://api.example.com');
    expect(config.basePath).toBe('/devpilot');
    expect(config.apiUnavailable).toBe(false);
  });

  it('falls back to the local API on loopback hosts', () => {
    expect(readRuntimeConfig(fakeWindow('localhost')).apiBaseUrl).toBe('http://localhost:8000');
    expect(readRuntimeConfig(fakeWindow('127.0.0.1')).apiBaseUrl).toBe('http://localhost:8000');
  });

  it('prefers an explicit origin over the loopback fallback', () => {
    const config = readRuntimeConfig(
      fakeWindow('localhost', { apiBaseUrl: 'https://staging.example.com' }),
    );

    expect(config.apiBaseUrl).toBe('https://staging.example.com');
  });

  it('flags a production build with no API origin as unavailable', () => {
    const config = readRuntimeConfig(fakeWindow('devpilot.example.com'));

    expect(config.apiBaseUrl).toBe('');
    expect(config.apiUnavailable).toBe(true);
  });

  it('normalizes the base path', () => {
    expect(normalizeBasePath('/')).toBe('');
    expect(normalizeBasePath('devpilot/')).toBe('/devpilot');
    expect(normalizeBasePath('/a/b/')).toBe('/a/b');
  });
});
