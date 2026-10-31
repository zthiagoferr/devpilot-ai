import { describe, expect, it } from 'vitest';

import {
  causeLabel,
  issueLocation,
  originBadge,
  severityLabel,
  severityTone,
  sortIssues,
} from './issue-presentation';

describe('issue presentation', () => {
  it('translates known causes and falls back to the stable code', () => {
    expect(causeLabel({ message: 'x', cause: 'missing_alt' })).toBe('Imagem sem texto alternativo');
    expect(causeLabel({ message: 'x', cause: 'unclosed_block' })).toBe('Bloco sem fechamento');
    expect(causeLabel({ message: 'x', cause: 'new_validator_code' })).toBe('new_validator_code');
    expect(causeLabel({ message: 'x', code: 'unbalanced_braces' })).toBe('Chaves desbalanceadas');
    expect(causeLabel({ message: 'x' })).toBe('');
  });

  it('translates the causes added by the multi-language validators', () => {
    const labels: ReadonlyArray<[string, string]> = [
      ['undefined_name', 'Nome não definido'],
      ['division_by_zero', 'Divisão por zero'],
      ['incompatible_operand_types', 'Tipos de operandos incompatíveis'],
      ['index_out_of_range', 'Índice fora do intervalo'],
      ['control_flow', 'Fluxo de controle suspeito'],
      ['break_outside_loop', 'break fora de laço'],
      ['continue_outside_loop', 'continue fora de laço'],
      ['duplicate_dict_key', 'Chave duplicada no dicionário'],
      ['unverified_totvs_api', 'Identificador TOTVS/Protheus não verificado'],
      ['assignment_in_condition', 'Atribuição em condição'],
      ['loop_without_progress', 'Laço sem progresso'],
      ['suspicious_loose_equality', 'Comparação solta (==) suspeita'],
      ['nan_comparison', 'Comparação com NaN'],
      ['undeclared_reference', 'Referência não declarada'],
      ['invalid_value', 'Valor CSS inválido'],
      ['unknown_property', 'Propriedade CSS desconhecida'],
      ['invalid_unit', 'Unidade CSS inválida'],
      ['missing_title', 'Título do documento ausente'],
      ['unsafe_target_blank', 'Link com target="_blank" sem rel seguro'],
      ['button_without_label', 'Botão sem rótulo acessível'],
      ['undeclared_variable', 'Variável não declarada'],
      ['deprecated_api', 'API obsoleta'],
      ['obsolete_include', 'Include obsoleto'],
      ['include_case_convention', 'Convenção de caixa no include'],
      ['api_in_loop', 'API chamada dentro de laço'],
      ['ui_call_in_transaction', 'Interação de UI dentro de transação'],
      ['direct_metadata_access', 'Acesso direto a metadados do Protheus'],
      ['naming_convention', 'Convenção de nomes ADVPL'],
    ];

    for (const [cause, label] of labels) {
      expect(causeLabel({ message: 'x', cause })).toBe(label);
    }
  });

  it('formats file:line:column with partial locations', () => {
    expect(issueLocation({ message: 'x', file: 'src/app.prg', line: 2, column: 4 })).toBe(
      'src/app.prg:2:4',
    );
    expect(issueLocation({ message: 'x', file: 'src/app.prg', line: 2 })).toBe('src/app.prg:2');
    expect(issueLocation({ message: 'x', line: 2, column: 4 }, 'fallback.py')).toBe(
      'fallback.py:2:4',
    );
    expect(issueLocation({ message: 'x', line: 2, column: 4 })).toBe('Linha 2, coluna 4');
    expect(issueLocation({ message: 'x' })).toBe('');
  });

  it('maps severity labels and tones', () => {
    expect(severityLabel({ message: 'x', severity: 'error' })).toBe('Alta');
    expect(severityTone({ message: 'x', severity: 'critical' })).toBe('danger');
    expect(severityTone({ message: 'x', severity: 'warning' })).toBe('warning');
    expect(severityTone({ message: 'x', severity: 'info' })).toBe('info');
    expect(severityLabel({ message: 'x', severity: 'custom' })).toBe('custom');
  });

  it('labels heuristic, AI and mixed origins without claiming an official build', () => {
    expect(originBadge({ message: 'x', origin: 'validator' })).toEqual({
      label: 'Validação local (heurística)',
      tone: 'neutral',
    });
    expect(originBadge({ message: 'x', analysis_kind: 'heuristic_validation' })).toEqual({
      label: 'Validação local (heurística)',
      tone: 'neutral',
    });
    expect(originBadge({ message: 'x', origin: 'ai' })).toEqual({
      label: 'Sugestão de IA',
      tone: 'warning',
    });
    expect(originBadge({ message: 'x', origin: 'mixed' })).toEqual({
      label: 'Validação local + IA',
      tone: 'info',
    });
    expect(originBadge({ message: 'x' })).toBeNull();
  });

  it('sorts by severity without mutating the input', () => {
    const issues = [
      { message: 'info', severity: 'info' },
      { message: 'critical', severity: 'critical' },
      { message: 'medium', severity: 'medium' },
    ];
    const sorted = sortIssues(issues);

    expect(sorted.map((issue) => issue.message)).toEqual(['critical', 'medium', 'info']);
    expect(issues[0]?.message).toBe('info');
  });
});
