import { Analysis } from './api.types';

/** Short pt-BR summary shared by the manual and repository result panels. */
export function analysisSuccessMessage(analysis: Analysis): string {
  const score = analysis.result?.score;
  const validationSkipped = analysis.result?.validation_skipped === true;
  const scoreStatus = analysis.result?.score_status;
  const notEvaluated =
    validationSkipped || scoreStatus === 'skipped' || scoreStatus === 'unavailable';
  const issueCount = analysis.result?.issues?.length ?? 0;
  const parts = [analysis.status === 'completed' ? 'Análise concluída.' : 'Análise finalizada.'];

  // A neutral 100 from a skipped validation (or an error score) is not an
  // evaluation and must not be announced as one.
  if (!notEvaluated && typeof score === 'number' && Number.isFinite(score)) {
    parts.push(`Score ${score}/100.`);
  }
  parts.push(
    issueCount === 0
      ? 'Nenhum problema encontrado.'
      : `${issueCount} ${issueCount === 1 ? 'problema encontrado' : 'problemas encontrados'}.`,
  );
  return parts.join(' ');
}
