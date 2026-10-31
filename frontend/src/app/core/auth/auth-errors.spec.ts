import { describe, expect, it } from 'vitest';

import {
  AUTH_GENERIC_MESSAGE,
  authErrorCode,
  emailFromAuthError,
  mapAuthError,
  pendingCredentialFrom,
} from './auth-errors';

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

  it.each([
    [
      'auth/operation-not-allowed',
      'Este método de acesso não está habilitado no projeto Firebase.',
    ],
    ['auth/credential-already-in-use', 'Esta credencial já está vinculada a outra conta.'],
    ['auth/provider-already-linked', 'Este provedor já está vinculado à sua conta.'],
    ['auth/user-mismatch', 'As credenciais informadas não correspondem ao usuário atual.'],
    [
      'auth/argument-error',
      'Não foi possível concluir o acesso. Verifique os dados e tente novamente.',
    ],
    ['auth/invalid-continue-uri', 'O endereço de retorno informado é inválido.'],
    ['auth/unauthorized-continue-uri', 'O endereço de retorno não está autorizado no Firebase.'],
    ['auth/missing-continue-uri', 'O endereço de retorno é obrigatório.'],
    [
      'auth/operation-not-supported-in-this-environment',
      'Este navegador não suporta a janela de acesso do GitHub. Tente outro navegador.',
    ],
  ])('maps the new code %s to a pt-BR message', (code, expected) => {
    expect(mapAuthError({ code })).toBe(expected);
  });

  it('uses the provider label in popup and operation-not-allowed messages', () => {
    expect(mapAuthError({ code: 'auth/popup-closed-by-user' }, { providerLabel: 'Google' })).toBe(
      'A janela de acesso do Google foi fechada antes de concluir o acesso.',
    );
    expect(mapAuthError({ code: 'auth/popup-blocked' }, { providerLabel: 'Apple' })).toBe(
      'O navegador bloqueou a janela de acesso do Apple.',
    );
    expect(
      mapAuthError({ code: 'auth/operation-not-allowed' }, { providerLabel: 'Microsoft' }),
    ).toBe('A entrada com Microsoft não está habilitada no projeto Firebase.');
    expect(
      mapAuthError(
        { code: 'auth/operation-not-supported-in-this-environment' },
        { providerLabel: 'GitHub' },
      ),
    ).toBe('Este navegador não suporta a janela de acesso do GitHub. Tente outro navegador.');
  });

  it('mentions the existing method for account-exists-with-different-credential', () => {
    expect(
      mapAuthError(
        { code: 'auth/account-exists-with-different-credential' },
        { existingMethod: 'Google' },
      ),
    ).toBe('Este e-mail já usa Google.');
    expect(mapAuthError({ code: 'auth/account-exists-with-different-credential' })).toBe(
      'Este e-mail já usa outro método de acesso.',
    );
  });

  it('falls back to a generic message for unknown or missing codes', () => {
    expect(mapAuthError({ code: 'auth/unknown' })).toBe(AUTH_GENERIC_MESSAGE);
    expect(mapAuthError(new Error('boom'))).toBe(AUTH_GENERIC_MESSAGE);
    expect(authErrorCode({ code: 42 })).toBeNull();
  });
});

describe('emailFromAuthError', () => {
  it('reads the direct email and the customData fallback', () => {
    expect(emailFromAuthError({ email: 'direct@example.com' })).toBe('direct@example.com');
    expect(emailFromAuthError({ customData: { email: 'custom@example.com' } })).toBe(
      'custom@example.com',
    );
  });

  it('returns null when no address is present', () => {
    expect(emailFromAuthError(null)).toBeNull();
    expect(emailFromAuthError({ code: 'auth/unknown' })).toBeNull();
    expect(emailFromAuthError({ email: '' })).toBeNull();
    expect(emailFromAuthError({ customData: { email: 42 } })).toBeNull();
  });
});

describe('pendingCredentialFrom', () => {
  it('returns a structurally valid AuthCredential and nothing else', () => {
    const credential = { providerId: 'google.com', signInMethod: 'google.com' };
    expect(pendingCredentialFrom({ credential })).toBe(credential);
    expect(pendingCredentialFrom({ credential: { providerId: 'google.com' } })).toBeNull();
    expect(pendingCredentialFrom({ credential: 'not-a-credential' })).toBeNull();
    expect(pendingCredentialFrom(null)).toBeNull();
  });
});
