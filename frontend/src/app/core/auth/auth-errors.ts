/**
 * Firebase Auth error code -> pt-BR message.
 *
 * Every code the UI can surface is mapped here so the raw SDK text (usually
 * English and sometimes technical) never reaches the user. Unknown codes fall
 * back to a generic retry message.
 */
export const AUTH_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  'auth/invalid-credential': 'E-mail ou senha inválidos.',
  'auth/invalid-email': 'Informe um e-mail válido.',
  'auth/missing-password': 'Informe sua senha.',
  'auth/missing-email': 'Informe o e-mail da conta.',
  'auth/weak-password': 'A senha é muito fraca. Use ao menos 6 caracteres.',
  'auth/email-already-in-use': 'Este e-mail já está cadastrado. Tente entrar.',
  'auth/user-not-found': 'Não encontramos uma conta com este e-mail.',
  'auth/wrong-password': 'Senha incorreta.',
  'auth/user-disabled': 'Esta conta está desativada.',
  'auth/too-many-requests': 'Muitas tentativas. Aguarde alguns instantes e tente novamente.',
  'auth/network-request-failed': 'Falha de rede. Verifique sua conexão e tente novamente.',
  'auth/operation-not-allowed': 'Este método de acesso não está habilitado no projeto Firebase.',
  'auth/invalid-api-key':
    'A chave pública do Firebase é inválida. Revise a configuração do projeto.',
  'auth/api-key-not-valid.-please-pass-a-valid-api-key.':
    'A chave pública do Firebase é inválida. Revise a configuração do projeto.',
  'auth/popup-closed-by-user': 'A janela do GitHub foi fechada antes de concluir o acesso.',
  'auth/popup-blocked': 'O navegador bloqueou a janela do GitHub.',
  'auth/cancelled-popup-request': 'Já existe uma janela de acesso aberta.',
  'auth/account-exists-with-different-credential': 'Este e-mail já usa outro método de acesso.',
  'auth/requires-recent-login': 'Entre novamente para concluir esta ação.',
  'auth/unauthorized-domain': 'Este domínio não está autorizado no Firebase Authentication.',
  'auth/operation-not-supported-in-this-environment':
    'Este navegador não suporta a janela de acesso do GitHub. Tente outro navegador.',
};

export const AUTH_UNAVAILABLE_MESSAGE =
  'A autenticação não está configurada neste ambiente. Você pode analisar seu código sem entrar.';

export const LOGIN_UNAVAILABLE_MESSAGE =
  'Login não disponível: a autenticação não está configurada neste ambiente. Você pode analisar código sem conta.';

/** SDK bootstrap failed (invalid key, network, missing provider). */
export const LOGIN_AUTH_ERROR_MESSAGE =
  'Login indisponível: não foi possível inicializar a autenticação neste ambiente. Você pode analisar código sem conta.';

/** The SDK is still loading; opening the dialog now would offer a dead form. */
export const LOGIN_INITIALIZING_MESSAGE =
  'A autenticação ainda está inicializando. Tente novamente em instantes ou analise seu código sem conta.';

export const AUTH_GENERIC_MESSAGE = 'Não foi possível concluir a operação. Tente novamente.';

export interface AuthLikeError {
  readonly code?: unknown;
}

/** Extracts the `auth/*` code from an unknown SDK error, if there is one. */
export function authErrorCode(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = (error as AuthLikeError).code;
    if (typeof code === 'string' && code !== '') {
      return code;
    }
  }
  return null;
}

export function mapAuthError(error: unknown): string {
  const code = authErrorCode(error);
  if (code === null) {
    return AUTH_GENERIC_MESSAGE;
  }
  return AUTH_ERROR_MESSAGES[code] ?? AUTH_GENERIC_MESSAGE;
}
