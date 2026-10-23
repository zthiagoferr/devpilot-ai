import { describe, expect, it } from 'vitest';

import { AUTH_GENERIC_MESSAGE, authErrorCode, mapAuthError } from './auth-errors';

describe('mapAuthError', () => {
  it.each([
    ['auth/invalid-credential', 'E-mail ou senha inválidos.'],
    ['auth/email-already-in-use', 'Este e-mail já está cadastrado. Tente entrar.'],
    ['auth/weak-password', 'A senha é muito fraca. Use ao menos 6 caracteres.'],
    ['auth/too-many-requests', 'Muitas tentativas. Aguarde alguns instantes e tente novamente.'],
    ['auth/popup-closed-by-user', 'A janela do GitHub foi fechada antes de concluir o acesso.'],
    ['auth/network-request-failed', 'Falha de rede. Verifique sua conexão e tente novamente.'],
    [
      'auth/invalid-api-key',
      'A chave pública do Firebase é inválida. Revise a configuração do projeto.',
    ],
  ])('maps %s to a pt-BR message', (code, expected) => {
    expect(mapAuthError({ code })).toBe(expected);
  });

  it('falls back to a generic message for unknown or missing codes', () => {
    expect(mapAuthError({ code: 'auth/unknown' })).toBe(AUTH_GENERIC_MESSAGE);
    expect(mapAuthError(new Error('boom'))).toBe(AUTH_GENERIC_MESSAGE);
    expect(authErrorCode({ code: 42 })).toBeNull();
  });
});
