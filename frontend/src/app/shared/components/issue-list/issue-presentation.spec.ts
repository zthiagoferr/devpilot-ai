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
