import { computed, inject, Injectable, InjectionToken } from '@angular/core';

import { AppConfig, readRuntimeConfig } from './app-config';

/** Injection token for tests and for future per-environment overrides. */
export const APP_CONFIG = new InjectionToken<AppConfig>('APP_CONFIG', {
  providedIn: 'root',
  factory: () => readRuntimeConfig(),
});

@Injectable({ providedIn: 'root' })
export class ConfigService {
  private readonly runtime = inject(APP_CONFIG);

  readonly apiBaseUrl = this.runtime.apiBaseUrl;
  readonly basePath = this.runtime.basePath;
  readonly apiUnavailable = this.runtime.apiUnavailable;
  readonly hasApi = computed(() => this.apiBaseUrl !== '');
}
