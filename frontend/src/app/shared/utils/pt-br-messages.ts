/**
 * Presentation-only pt-BR messages (ADR A-7).
 *
 * The API keeps its contract in English; the dashboard translates the known
 * deterministic summaries and composes a local message for anything unknown so
 * an English backend phrase never becomes the main title of a result panel.
 */

export interface AnalysisSummaryContext {
  readonly summary?: string | null;
  readonly score?: number | null;
  readonly issueCount?: number | null;
  readonly status?: string | null;
}

const STRUCTURAL_LANGUAGES: Readonly<Record<string, string>> = {
  HTML: 'HTML',
  CSS: 'CSS',
  JavaScript: 'JavaScript',
};

const KNOWN_SUMMARIES: ReadonlyArray<{
  readonly pattern: RegExp;
  readonly build: (match: RegExpMatchArray) => string;
}> = [
  {
    pattern:
      /^Analysis completed with an overall score of (\d+)\/100 and (\d+) issue\(s\) found\.$/,
    build: (match) =>
      `Análise concluída com score geral de ${match[1]}/100 e ${issues(match[2] ?? '0')}.`,
  },
  {
    pattern: /^(?:The )?[Aa]nalysis could not be completed\.$/,
    build: () => 'Não foi possível concluir a análise.',
  },
  {
    pattern: /^No analysis results were provided\.$/,
    build: () => 'Nenhum resultado de análise foi fornecido.',
  },
  {
    pattern: /^Structural validation could not be completed\.$/,
    build: () => 'Não foi possível concluir a validação estrutural.',
  },
  {
    pattern: /^Language detection did not select a structural validator\.$/,
    build: () => 'A detecção de linguagem não selecionou um validador estrutural.',
  },
  {
    pattern: /^(HTML|CSS|JavaScript) structural checks found no issues\.$/,
    build: (match) =>
      `Verificações estruturais de ${STRUCTURAL_LANGUAGES[match[1] ?? ''] ?? match[1]} não encontraram problemas.`,
  },
  {
    pattern: /^(HTML|CSS|JavaScript) structural checks reported (\d+) issue\(s\)\.$/,
    build: (match) =>
      `Verificações estruturais de ${STRUCTURAL_LANGUAGES[match[1] ?? ''] ?? match[1]} encontraram ${problems(match[2] ?? '0')}.`,
  },
  {
    pattern: /^No structural issues were found in the ADVPL source\.$/,
    build: () => 'Nenhum problema estrutural encontrado no código ADVPL.',
  },
  {
    pattern: /^Structural analysis reported (\d+) issue\(s\)\.$/,
    build: (match) => `A análise estrutural encontrou ${issues(match[1] ?? '0')}.`,
  },
  {
    pattern: /^Python syntax parsing completed without errors\.$/,
    build: () => 'Sintaxe Python analisada sem erros.',
  },
  {
    pattern: /^Python syntax parsing reported an error\.$/,
    build: () => 'A análise de sintaxe Python encontrou um erro.',
  },
  {
    pattern: /^Valid Python code containing (\d+) function\(s\) and (\d+) class\(es\)\.$/,
    build: (match) => `Código Python válido com ${match[1]} função(ões) e ${match[2]} classe(s).`,
  },
  {
    pattern: /^Python syntax error detected\.$/,
    build: () => 'Erro de sintaxe Python detectado.',
  },
  {
    pattern: /^Python test syntax error detected\.$/,
    build: () => 'Erro de sintaxe detectado nos testes Python.',
  },
  {
    pattern: /^Python syntax error prevented documentation analysis\.$/,
    build: () => 'O erro de sintaxe Python impediu a análise de documentação.',
  },
  {
    pattern: /^Found (\d+) test function\(s\) and (\d+) assert statement\(s\)\.$/,
    build: (match) =>
      `Foram encontradas ${match[1]} função(ões) de teste e ${match[2]} asserção(ões).`,
  },
  {
    pattern: /^Found (\d+) documentable object\(s\); (\d+) documented\.$/,
    build: (match) =>
      `Foram encontrados ${match[1]} objeto(s) documentável(is); ${match[2]} documentado(s).`,
  },
];

/** Translate a known backend summary or compose a local pt-BR fallback. */
export function analysisSummaryPtBr(context: AnalysisSummaryContext): string {
  const raw = (context.summary ?? '').trim();
  for (const entry of KNOWN_SUMMARIES) {
    const match = raw.match(entry.pattern);
    if (match !== null) {
      return entry.build(match);
    }
  }
  return composedSummary(context);
}

export type PostValidationStatus = 'passed' | 'failed' | 'not_run';

export const REPOSITORY_EMPTY_MESSAGE =
  'Nenhum arquivo Python, ADVPL, HTML5, CSS3 ou JavaScript elegível foi encontrado neste repositório.';

/**
 * Message shown when a repository has no analyzable file.
 *
 * The API contract is English-only, so any unexpected text would leak English
 * into the dashboard. Only text that is already the local pt-BR message is
 * kept; everything else (the known default and any future/unknown message)
 * falls back to the local text.
 */
export function repositoryEmptyMessagePtBr(message?: string | null): string {
  const raw = (message ?? '').trim();
  return raw === REPOSITORY_EMPTY_MESSAGE ? raw : REPOSITORY_EMPTY_MESSAGE;
}

const PASSED_MESSAGE =
  'Validação local (heurística) aprovada: o problema alvo foi resolvido e nenhum erro novo foi detectado.';
const NOT_RUN_MESSAGE = 'Validação local não executada para esta linguagem.';
const FAILED_FALLBACK =
  'Validação local (heurística) reprovada: o problema alvo não foi resolvido ou surgiram novos erros. Revise o código antes de decidir.';

const FAILED_REASONS: ReadonlyArray<{
  readonly pattern: RegExp;
  readonly build: (match: RegExpMatchArray) => string;
}> = [
  {
    pattern: /^the target issue is still reported by the local validator$/,
    build: () => 'o problema alvo ainda é apontado pelo validador local',
  },
  {
    pattern: /^(\d+) new high-severity finding(?:\(s\)|s)? (?:were|was) introduced$/,
    build: (match) => `${match[1]} novo(s) achado(s) de alta severidade foram introduzidos`,
  },
  {
    pattern:
      /^(\d+) new TOTVS\/Protheus identifier\(s\) could not be verified because no Protheus version was provided$/,
    build: (match) =>
      `${match[1]} novo(s) identificador(es) TOTVS/Protheus não pôde(ram) ser verificado(s) porque nenhuma versão do Protheus foi informada`,
  },
  {
    pattern: /^the corrected code is identical to the original file(?:,.*)?$/,
    build: () =>
      'o código corrigido é idêntico ao arquivo original, então o problema da linha de base persiste mesmo que o alvo não tenha sido reportado novamente',
  },
];

/** Build the pt-BR presentation of a post-validation result. */
export function postValidationMessage(
  status: PostValidationStatus | string | null | undefined,
  summary?: string | null,
): string {
  if (status === 'passed') {
    return PASSED_MESSAGE;
  }
  if (status !== 'failed') {
    return NOT_RUN_MESSAGE;
  }

  const reasons = failedReasons(summary ?? '');
  return reasons.length === 0
    ? FAILED_FALLBACK
    : `Validação local (heurística) reprovada: ${reasons.join('; ')}.`;
}

function composedSummary(context: AnalysisSummaryContext): string {
  const score =
    typeof context.score === 'number' && Number.isFinite(context.score)
      ? `score ${Math.round(context.score)}/100`
      : null;
  const count =
    typeof context.issueCount === 'number' && Number.isFinite(context.issueCount)
      ? Math.max(0, Math.round(context.issueCount))
      : null;
  const issueText =
    count === null ? null : count === 0 ? 'nenhum problema encontrado' : issues(String(count));

  const parts = [context.status === 'failed' ? 'Análise finalizada' : 'Análise concluída'];
  if (score !== null) {
    parts.push(`com ${score}`);
  }
  if (issueText !== null) {
    parts.push(`e ${issueText}`);
  }
  return `${parts.join(' ')}.`;
}

function issues(value: string): string {
  const count = Number.parseInt(value, 10);
  if (!Number.isFinite(count)) {
    return 'problemas encontrados';
  }
  return `${count} ${count === 1 ? 'problema encontrado' : 'problemas encontrados'}`;
}

function problems(value: string): string {
  const count = Number.parseInt(value, 10);
  if (!Number.isFinite(count)) {
    return 'problemas';
  }
  return `${count} ${count === 1 ? 'problema' : 'problemas'}`;
}

function failedReasons(summary: string): string[] {
  const prefix = 'Correction failed local validation: ';
  const suffix = 'This is a deterministic local check, not an official Protheus validation.';
  const trimmed = summary.trim();
  if (!trimmed.startsWith(prefix)) {
    return [];
  }

  let rawReasons = trimmed.slice(prefix.length).trim();
  if (rawReasons.endsWith(suffix)) {
    rawReasons = rawReasons.slice(0, -suffix.length).trim();
  }
  rawReasons = rawReasons.replace(/\.$/, '').trim();
  if (rawReasons === '') {
    return [];
  }

  const translated = rawReasons
    .split(';')
    .map((reason) => reason.trim())
    .map((reason) => translateFailedReason(reason));

  // An unknown reason is not silently dropped: fall back to a complete local
  // explanation instead of showing a partial diagnosis.
  return translated.every((reason): reason is string => reason !== null) ? translated : [];
}

function translateFailedReason(reason: string): string | null {
  for (const entry of FAILED_REASONS) {
    const match = reason.match(entry.pattern);
    if (match !== null) {
      return entry.build(match);
    }
  }
  return null;
}
