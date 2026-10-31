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
  'auth/credential-already-in-use': 'Esta credencial já está vinculada a outra conta.',
  'auth/provider-already-linked': 'Este provedor já está vinculado à sua conta.',
  'auth/user-mismatch': 'As credenciais informadas não correspondem ao usuário atual.',
  'auth/argument-error':
    'Não foi possível concluir o acesso. Verifique os dados e tente novamente.',
  'auth/invalid-continue-uri': 'O endereço de retorno informado é inválido.',
  'auth/unauthorized-continue-uri': 'O endereço de retorno não está autorizado no Firebase.',
  'auth/missing-continue-uri': 'O endereço de retorno é obrigatório.',
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

/** Optional context that turns a generic message into a provider-specific one. */
export interface AuthErrorContext {
  /** pt-BR label of the provider the user tried (e.g. "Google"). */
  readonly providerLabel?: string;
  /** Human label of the account's existing method (e.g. "Google"). */
  readonly existingMethod?: string;
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

function contextualMessage(code: string, context: AuthErrorContext): string | null {
  const label = context.providerLabel?.trim() ?? '';
  if (label !== '' && code === 'auth/operation-not-allowed') {
    return `A entrada com ${label} não está habilitada no projeto Firebase.`;
  }
  if (
    context.existingMethod !== undefined &&
    code === 'auth/account-exists-with-different-credential'
  ) {
    return `Este e-mail já usa ${context.existingMethod}.`;
  }
  if (label !== '') {
    switch (code) {
      case 'auth/popup-closed-by-user':
        return `A janela de acesso do ${label} foi fechada antes de concluir o acesso.`;
      case 'auth/popup-blocked':
        return `O navegador bloqueou a janela de acesso do ${label}.`;
      case 'auth/operation-not-supported-in-this-environment':
        return `Este navegador não suporta a janela de acesso do ${label}. Tente outro navegador.`;
    }
  }
  return null;
}

export function mapAuthError(error: unknown, context: AuthErrorContext = {}): string {
  const code = authErrorCode(error);
  if (code === null) {
    return AUTH_GENERIC_MESSAGE;
  }
  return contextualMessage(code, context) ?? AUTH_ERROR_MESSAGES[code] ?? AUTH_GENERIC_MESSAGE;
}

/** Reads the address carried by a Firebase error (`email` or `customData.email`). */
export function emailFromAuthError(error: unknown): string | null {
  if (typeof error !== 'object' || error === null) {
    return null;
  }
  const direct = (error as { email?: unknown }).email;
  if (typeof direct === 'string' && direct !== '') {
    return direct;
  }
  const customData = (error as { customData?: unknown }).customData;
  if (typeof customData === 'object' && customData !== null) {
    const email = (customData as { email?: unknown }).email;
    if (typeof email === 'string' && email !== '') {
      return email;
    }
  }
  return null;
}

/**
 * Extracts the pending credential from an `account-exists-with-different-
 * credential` error.
 *
 * The credential is held in memory only (never persisted) and can be linked
 * later in the same tab/session.
 */
export function pendingCredentialFrom(
  error: unknown,
): import('firebase/auth').AuthCredential | null {
  if (typeof error !== 'object' || error === null) {
    return null;
  }
  const credential = (error as { credential?: unknown }).credential;
  if (typeof credential !== 'object' || credential === null) {
    return null;
  }
  const providerId = (credential as { providerId?: unknown }).providerId;
  const signInMethod = (credential as { signInMethod?: unknown }).signInMethod;
  if (typeof providerId !== 'string' || typeof signInMethod !== 'string') {
    return null;
  }
  return credential as import('firebase/auth').AuthCredential;
}
