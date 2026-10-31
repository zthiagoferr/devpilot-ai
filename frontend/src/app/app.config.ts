import { registerLocaleData } from '@angular/common';
import localePt from '@angular/common/locales/pt';
import {
  ApplicationConfig,
  LOCALE_ID,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import {
  provideRouter,
  withComponentInputBinding,
  withHashLocation,
  withInMemoryScrolling,
} from '@angular/router';

import { routes } from './app.routes';
import { AUTH_TOKEN_PROVIDER } from './core/auth/auth-token.provider';
import { AuthService } from './core/auth/auth.service';

registerLocaleData(localePt, 'pt-BR');

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    { provide: LOCALE_ID, useValue: 'pt-BR' },
    {
      // The bearer token is read immediately before every API request; Firebase
      // refreshes it when it is close to expiry. `null` means "visitor".
      provide: AUTH_TOKEN_PROVIDER,
      useFactory:
        (auth: AuthService) =>
        (force = false) =>
          auth.getToken(force),
      deps: [AuthService],
    },
    // Starts restoring the Firebase session before the first screen renders.
    // The promise is intentionally not awaited: a slow network must never block
    // the app, and the history/overview screens wait for `auth.ready()` before
    // requesting owner-scoped data. The SDK stays in a lazy chunk.
    provideAppInitializer(() => {
      void inject(AuthService).initialize();
    }),
    provideRouter(
      routes,
      withHashLocation(),
      withComponentInputBinding(),
      withInMemoryScrolling({
        scrollPositionRestoration: 'enabled',
        anchorScrolling: 'enabled',
      }),
    ),
  ],
};
