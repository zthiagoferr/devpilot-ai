import { AnalysisIssue, CorrectionIssueRef } from '../../../core/api/api.types';

/** Maps a displayed analysis issue to the correction target contract. */
export function toIssueRef(issue: AnalysisIssue): CorrectionIssueRef {
  return {
    message: issue.message,
    severity: issue.severity ?? 'info',
    ...(typeof issue.line === 'number' ? { line: issue.line } : {}),
    ...(typeof issue.column === 'number' ? { column: issue.column } : {}),
    ...(issue.rule_id ? { rule_id: issue.rule_id } : {}),
    ...(issue.code ? { code: issue.code } : {}),
    ...(issue.cause ? { cause: issue.cause } : {}),
  };
}
