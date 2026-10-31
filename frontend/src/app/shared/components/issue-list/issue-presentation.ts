import { AnalysisIssue } from '../../../core/api/api.types';
import { BadgeTone } from '../badge/badge.component';

import { languageLabel } from '../language-select/language-options';

export interface IssueBadge {
  readonly label: string;
  readonly tone: BadgeTone;
}

export const ADVPL_DISCLAIMER = 'Análise estática — não valida compilação.';

const SEVERITY_LABELS: Readonly<Record<string, string>> = {
  critical: 'Crítica',
  high: 'Alta',
  error: 'Alta',
  medium: 'Média',
  warning: 'Média',
  low: 'Baixa',
  info: 'Informativa',
};

const SEVERITY_RANK: Readonly<Record<string, number>> = {
  critical: 0,
  high: 1,
  error: 1,
  medium: 2,
  warning: 2,
  low: 3,
  info: 4,
};

/**
 * PT-BR descriptions for the stable `cause` codes emitted by the deterministic
 * validators. Unknown codes fall back to the code itself so a new validator
 * never disappears from the UI.
 */
const CAUSE_LABELS: Readonly<Record<string, string>> = {
  // detection
  language_low_confidence: 'Linguagem detectada com baixa confiança',
  language_undetected: 'Linguagem não identificada',
  validator_error: 'Falha na validação local',
  python_syntax: 'Erro de sintaxe Python',
  // Python (Fase B)
  undefined_name: 'Nome não definido',
  division_by_zero: 'Divisão por zero',
  incompatible_operand_types: 'Tipos de operandos incompatíveis',
  index_out_of_range: 'Índice fora do intervalo',
  control_flow: 'Fluxo de controle suspeito',
  break_outside_loop: 'break fora de laço',
  continue_outside_loop: 'continue fora de laço',
  duplicate_dict_key: 'Chave duplicada no dicionário',
  // generic/scanners
  unbalanced_braces: 'Chaves desbalanceadas',
  unbalanced_if: 'Bloco IF desbalanceado',
  unbalanced_delimiters: 'Delimitadores desbalanceados',
  unbalanced_parentheses: 'Parênteses desbalanceados',
  json_only: 'Conteúdo JSON não é JavaScript válido',
  reference_missing: 'Referência não encontrada no repositório',
  reference_unknown: 'Referência não verificada (árvore incompleta)',
  unverified_totvs_api: 'Identificador TOTVS/Protheus não verificado',
  // HTML
  duplicate_id: 'ID duplicado no documento',
  missing_alt: 'Imagem sem texto alternativo',
  missing_label: 'Campo sem rótulo acessível',
  missing_doctype: 'DOCTYPE ausente',
  missing_html_tag: 'Elemento html ausente',
  missing_head_tag: 'Elemento head ausente',
  missing_body_tag: 'Elemento body ausente',
  missing_lang: 'Idioma do documento não informado',
  missing_viewport: 'Meta viewport ausente',
  missing_title: 'Título do documento ausente',
  unclosed_tag: 'Tag sem fechamento',
  unexpected_closing_tag: 'Fechamento inesperado de tag',
  unsafe_target_blank: 'Link com target="_blank" sem rel seguro',
  button_without_label: 'Botão sem rótulo acessível',
  // CSS
  duplicate_property: 'Propriedade CSS duplicada',
  empty_selector: 'Seletor CSS vazio',
  import_after_rules: '@import depois de outras regras',
  important_usage: 'Uso de !important',
  invalid_value: 'Valor CSS inválido',
  unknown_property: 'Propriedade CSS desconhecida',
  invalid_unit: 'Unidade CSS inválida',
  // JavaScript
  orphan_else: 'else sem if correspondente',
  redeclaration: 'Variável declarada novamente',
  duplicate_comma: 'Vírgula duplicada',
  empty_assignment: 'Atribuição sem valor',
  eval_usage: 'Uso de eval',
  debugger_statement: 'Instrução debugger',
  unterminated_string: 'String não terminada',
  unterminated_comment: 'Comentário não terminado',
  unterminated_template: 'Template não terminado',
  assignment_in_condition: 'Atribuição em condição',
  loop_without_progress: 'Laço sem progresso',
  suspicious_loose_equality: 'Comparação solta (==) suspeita',
  nan_comparison: 'Comparação com NaN',
  undeclared_reference: 'Referência não declarada',
  // ADVPL
  include_unresolved: 'Include não resolvido',
  undeclared_variable: 'Variável não declarada',
  deprecated_api: 'API obsoleta',
  obsolete_include: 'Include obsoleto',
  include_case_convention: 'Convenção de caixa no include',
  api_in_loop: 'API chamada dentro de laço',
  ui_call_in_transaction: 'Interação de UI dentro de transação',
  direct_metadata_access: 'Acesso direto a metadados do Protheus',
  naming_convention: 'Convenção de nomes ADVPL',
  unbalanced_ifdef: '#ifdef sem fechamento',
  unclosed_block: 'Bloco sem fechamento',
  unmatched_closer: 'Fechamento sem abertura correspondente',
  else_without_if: 'else sem if correspondente',
  elseif_without_if: 'elseif sem if correspondente',
  duplicate_function: 'Função duplicada',
  duplicate_define: '#define duplicado',
  missing_return: 'Retorno ausente',
  return_outside_function: 'return fora de função',
  default_outside_function: 'default fora de bloco',
  global_variable: 'Variável global',
};

export function severityRank(issue: AnalysisIssue): number {
  const severity = (issue.severity ?? '').trim().toLowerCase();
  return SEVERITY_RANK[severity] ?? 3;
}

export function severityLabel(issue: AnalysisIssue): string {
  const severity = (issue.severity ?? '').trim().toLowerCase();
  return SEVERITY_LABELS[severity] ?? (severity === '' ? 'Problema' : severity);
}

export function severityTone(issue: AnalysisIssue): BadgeTone {
  const rank = severityRank(issue);
  if (rank <= 1) {
    return 'danger';
  }
  if (rank === 2) {
    return 'warning';
  }
  return 'info';
}

/** Readable cause: a PT-BR label, or the stable code when not translated yet. */
export function causeLabel(issue: AnalysisIssue): string {
  const code = (issue.cause ?? issue.code ?? '').trim();
  if (code === '') {
    return '';
  }
  return CAUSE_LABELS[code] ?? code;
}

/** `arquivo:linha:coluna`, omitting the parts the issue does not carry. */
export function issueLocation(issue: AnalysisIssue, fallbackFile?: string | null): string {
  const file = (issue.file ?? fallbackFile ?? '').trim();
  const line = issue.line;
  const column = issue.column;
  const hasLine = typeof line === 'number' && Number.isFinite(line);
  const hasColumn = typeof column === 'number' && Number.isFinite(column);

  if (file === '') {
    if (hasLine && hasColumn) {
      return `Linha ${line}, coluna ${column}`;
    }
    return hasLine ? `Linha ${line}` : '';
  }
  if (hasLine && hasColumn) {
    return `${file}:${line}:${column}`;
  }
  return hasLine ? `${file}:${line}` : file;
}

/** Origin/validation badge; `null` when the backend sent no origin metadata. */
export function originBadge(issue: AnalysisIssue): IssueBadge | null {
  if (issue.origin === 'ai') {
    return { label: 'Sugestão de IA', tone: 'warning' };
  }
  if (issue.origin === 'mixed') {
    return { label: 'Validação local + IA', tone: 'info' };
  }
  if (issue.origin === 'validator' || issue.analysis_kind === 'heuristic_validation') {
    return { label: 'Validação local (heurística)', tone: 'neutral' };
  }
  if (issue.analysis_kind === 'official_validation') {
    return { label: 'Validação oficial', tone: 'success' };
  }
  return null;
}

export function issueLanguage(issue: AnalysisIssue, fallbackLanguage?: string | null): string {
  return (issue.language ?? fallbackLanguage ?? '').trim().toLowerCase();
}

export function isAdvplIssue(issue: AnalysisIssue, fallbackLanguage?: string | null): boolean {
  return issueLanguage(issue, fallbackLanguage) === 'advpl';
}

/** Language name used in the location line, or an empty string. */
export function issueLanguageLabel(issue: AnalysisIssue, fallbackLanguage?: string | null): string {
  const language = issueLanguage(issue, fallbackLanguage);
  return language === '' ? '' : languageLabel(language);
}

export function sortIssues(issues: readonly AnalysisIssue[]): readonly AnalysisIssue[] {
  return [...issues].sort((left, right) => severityRank(left) - severityRank(right));
}
