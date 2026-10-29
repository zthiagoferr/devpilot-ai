/** Maps HTTP failures to a single user-facing error shape. */

export type ApiErrorKind =
  | 'validation'
  | 'unauthorized'
  | 'forbidden'
  | 'not-found'
  | 'payload-too-large'
  | 'rate-limited'
  | 'server'
  | 'network'
  | 'unavailable'
  | 'invalid-response'
  | 'unknown';

export interface ApiErrorOptions {
  readonly status?: number;
  readonly fieldErrors?: Readonly<Record<string, string>>;
  readonly retryAfterSeconds?: number | null;
  readonly cause?: unknown;
  /**
   * Whether the error body was valid JSON. ``false`` identifies proxy HTML
   * pages (for example a suspended hosting service) that must not be parsed as
   * an API contract.
   */
  readonly bodyIsJson?: boolean;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly fieldErrors: Readonly<Record<string, string>>;
  readonly retryAfterSeconds: number | null;
  readonly bodyIsJson: boolean;

  constructor(kind: ApiErrorKind, message: string, options: ApiErrorOptions = {}) {
    super(message, { cause: options.cause });
    this.name = 'ApiError';
    this.kind = kind;
    this.status = options.status ?? null;
    this.fieldErrors = options.fieldErrors ?? {};
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.bodyIsJson = options.bodyIsJson ?? true;
  }
}

const UNKNOWN_MESSAGE = 'Não foi possível concluir a solicitação. Tente novamente.';

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function safeText(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed === '' ? null : trimmed;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (value === null || value === undefined) {
    return null;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return UNKNOWN_MESSAGE;
  }
}

/** Pulls the useful part out of FastAPI's `{"detail": ...}` envelope. */
function extractDetail(body: unknown): unknown {
  if (isRecord(body) && 'detail' in body) {
    return body['detail'];
  }
  return body;
}

function messageFromItem(item: unknown): string | null {
  if (typeof item === 'string') {
    return safeText(item);
  }
  if (isRecord(item)) {
    return safeText(item['msg'] ?? item['message'] ?? item['detail']);
  }
  return safeText(item);
}

function messagesFromDetail(detail: unknown): string[] {
  if (Array.isArray(detail)) {
    return detail.map(messageFromItem).filter((message): message is string => message !== null);
  }
  const single = messageFromItem(detail);
  return single === null ? [] : [single];
}

const LOCATION_PREFIXES = new Set(['body', 'query', 'path', 'header', 'cookie']);

function fieldErrorsFromDetail(detail: unknown): Record<string, string> {
  if (!Array.isArray(detail)) {
    return {};
  }

  const errors: Record<string, string> = {};
  for (const item of detail) {
    if (!isRecord(item)) {
      continue;
    }
    const message = messageFromItem(item);
    const location = item['loc'];
    if (message === null || !Array.isArray(location)) {
      continue;
    }
    const key = location
      .filter((part) => !(typeof part === 'string' && LOCATION_PREFIXES.has(part)))
      .map((part) => String(part))
      .join('.');
    if (key !== '' && errors[key] === undefined) {
      errors[key] = message;
    }
  }
  return errors;
}

/** Parses both the delay-seconds and the HTTP-date forms of `Retry-After`. */
export function parseRetryAfter(header: string | null | undefined): number | null {
  if (header === null || header === undefined) {
    return null;
  }

  const trimmed = header.trim();
  if (trimmed === '') {
    return null;
  }

  const seconds = Number(trimmed);
  if (Number.isFinite(seconds)) {
    return seconds < 0 ? 0 : Math.ceil(seconds);
  }

  const date = Date.parse(trimmed);
  if (Number.isNaN(date)) {
    return null;
  }
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) {
    return 'unauthorized';
  }
  if (status === 403) {
    return 'forbidden';
  }
  if (status === 404) {
    return 'not-found';
  }
  if (status === 413) {
    return 'payload-too-large';
  }
  if (status === 422) {
    return 'validation';
  }
  if (status === 429) {
    return 'rate-limited';
  }
  if (status >= 500) {
    return 'server';
  }
  return 'unknown';
}

export function mapErrorResponse(
  status: number,
  body: unknown,
  retryAfterHeader?: string | null,
  bodyIsJson = true,
): ApiError {
  const kind = kindForStatus(status);
  const detail = extractDetail(body);
  // A non-JSON body (proxy HTML, gateway page) has no contract to parse and
  // must never leak its markup into the user-facing message.
  const messages = bodyIsJson ? messagesFromDetail(detail) : [];
  const detailMessage = messages[0] ?? null;
  const fieldErrors = bodyIsJson ? fieldErrorsFromDetail(detail) : {};
  const retryAfterSeconds = parseRetryAfter(retryAfterHeader);

  let message: string;

  switch (kind) {
    case 'validation':
      message =
        messages.length > 0
          ? `Dados inválidos: ${messages.join(' ')}`
          : 'Dados inválidos. Revise os campos destacados e tente novamente.';
      break;
    case 'unauthorized':
      message = 'Sua sessão expirou ou não está autenticada. Entre novamente para continuar.';
      break;
    case 'forbidden':
      message = 'Você não tem permissão para acessar este recurso.';
      break;
    case 'not-found':
      message = 'Recurso não encontrado. Ele pode ter sido removido.';
      break;
    case 'payload-too-large':
      message =
        detailMessage ??
        'O código enviado excede o limite permitido pela API. Reduza o arquivo e tente novamente.';
      break;
    case 'rate-limited':
      message =
        retryAfterSeconds !== null
          ? `Muitas solicitações em pouco tempo. Tente novamente em ${retryAfterSeconds} s.`
          : 'Muitas solicitações em pouco tempo. Aguarde alguns instantes e tente novamente.';
      break;
    case 'server':
      message = 'A análise falhou no servidor. Tente novamente em instantes.';
      break;
    default:
      message = detailMessage ?? `Falha inesperada ao falar com a API (HTTP ${status}).`;
      break;
  }

  return new ApiError(kind, message, {
    status,
    fieldErrors,
    retryAfterSeconds,
    bodyIsJson,
  });
}

export function mapNetworkError(cause?: unknown): ApiError {
  return new ApiError(
    'network',
    'Não foi possível falar com a API. Verifique se o serviço está ativo e tente novamente.',
    { cause },
  );
}

export function mapUnavailableError(): ApiError {
  return new ApiError(
    'unavailable',
    'A API não está configurada para este ambiente. Configure a URL da API e recarregue a página.',
  );
}

export function mapInvalidResponseError(cause?: unknown): ApiError {
  return new ApiError(
    'invalid-response',
    'A API respondeu em um formato inesperado. Tente novamente.',
    { cause },
  );
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
