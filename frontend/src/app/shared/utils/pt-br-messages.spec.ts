import { describe, expect, it } from 'vitest';

import {
  REPOSITORY_EMPTY_MESSAGE,
  analysisSummaryPtBr,
  postValidationMessage,
  repositoryEmptyMessagePtBr,
} from './pt-br-messages';

describe('analysisSummaryPtBr', () => {
  it('translates the report summary with score and issue count', () => {
    expect(
      analysisSummaryPtBr({
        summary: 'Analysis completed with an overall score of 90/100 and 2 issue(s) found.',
        score: 90,
        issueCount: 2,
      }),
    ).toBe('Análise concluída com score geral de 90/100 e 2 problemas encontrados.');
  });

  it('translates the "no issues" structural summaries', () => {
    expect(
      analysisSummaryPtBr({
        summary: 'HTML structural checks found no issues.',
        issueCount: 0,
      }),
    ).toBe('Verificações estruturais de HTML não encontraram problemas.');
    expect(
      analysisSummaryPtBr({
        summary: 'JavaScript structural checks reported 1 issue(s).',
        issueCount: 1,
      }),
    ).toBe('Verificações estruturais de JavaScript encontraram 1 problema.');
  });

  it('translates the Python agent summaries', () => {
    expect(
      analysisSummaryPtBr({
        summary: 'Python syntax error detected.',
        score: 0,
        issueCount: 1,
      }),
    ).toBe('Erro de sintaxe Python detectado.');
    expect(
      analysisSummaryPtBr({
        summary: 'Valid Python code containing 2 function(s) and 1 class(es).',
        score: 100,
        issueCount: 0,
      }),
    ).toBe('Código Python válido com 2 função(ões) e 1 classe(s).');
  });

  it('composes a local pt-BR message for an unknown backend summary', () => {
    const message = analysisSummaryPtBr({
      summary: 'Some unexpected english sentence.',
      score: 42,
      issueCount: 3,
    });

    expect(message).toBe('Análise concluída com score 42/100 e 3 problemas encontrados.');
    expect(message).not.toContain('unexpected english');
  });

  it('handles an empty result without an English fallback', () => {
    expect(analysisSummaryPtBr({ summary: '', score: 100, issueCount: 0 })).toBe(
      'Análise concluída com score 100/100 e nenhum problema encontrado.',
    );
  });

  it('translates the exact backend failure message', () => {
    for (const summary of [
      'Analysis could not be completed.',
      'The analysis could not be completed.',
    ]) {
      expect(analysisSummaryPtBr({ summary, status: 'failed' })).toBe(
        'Não foi possível concluir a análise.',
      );
    }
  });
});

describe('repositoryEmptyMessagePtBr', () => {
  it('replaces the known English default with the local pt-BR message', () => {
    expect(
      repositoryEmptyMessagePtBr(
        'No eligible Python, ADVPL, HTML5, CSS3, or JavaScript files were found.',
      ),
    ).toContain('Nenhum arquivo Python');
    expect(repositoryEmptyMessagePtBr(null)).toContain('Nenhum arquivo Python');
  });

  it('falls back for an unexpected raw message instead of exposing English', () => {
    const message = repositoryEmptyMessagePtBr('Something unexpected happened.');

    expect(message).toBe(REPOSITORY_EMPTY_MESSAGE);
    expect(message).not.toContain('Something');
  });
});

describe('postValidationMessage', () => {
  it('uses the fixed pt-BR passed message', () => {
    expect(
      postValidationMessage(
        'passed',
        'Local structural validation no longer reports the target issue...',
      ),
    ).toBe(
      'Validação local (heurística) aprovada: o problema alvo foi resolvido e nenhum erro novo foi detectado.',
    );
  });

  it('explains a failed validation without exposing the English summary', () => {
    const message = postValidationMessage(
      'failed',
      'Correction failed local validation: the target issue is still reported by the local validator; 1 new high-severity finding(s) were introduced. This is a deterministic local check, not an official Protheus validation.',
    );

    expect(message).toBe(
      'Validação local (heurística) reprovada: o problema alvo ainda é apontado pelo validador local; 1 novo(s) achado(s) de alta severidade foram introduzidos.',
    );
    expect(message).not.toContain('Correction failed');
  });

  it('falls back to a complete local explanation for unknown reasons', () => {
    expect(postValidationMessage('failed', 'Correction failed local validation: mystery. ')).toBe(
      'Validação local (heurística) reprovada: o problema alvo não foi resolvido ou surgiram novos erros. Revise o código antes de decidir.',
    );
  });

  it('marks a validation that did not run for the language', () => {
    expect(postValidationMessage('not_run', 'The local structural validator did not run...')).toBe(
      'Validação local não executada para esta linguagem.',
    );
    expect(postValidationMessage(undefined)).toBe(
      'Validação local não executada para esta linguagem.',
    );
  });
});
