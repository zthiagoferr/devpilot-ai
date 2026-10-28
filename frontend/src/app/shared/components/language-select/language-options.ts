import { LanguageId } from '../../../core/api/api.types';

import { SelectOption } from '../select/select.component';

/** Language options shared by the analysis and repository forms. */
export const LANGUAGE_OPTIONS: readonly SelectOption[] = [
  { value: 'auto', label: 'Detectar automaticamente' },
  { value: 'python', label: 'Python' },
  { value: 'advpl', label: 'ADVPL' },
  { value: 'html', label: 'HTML5' },
  { value: 'css', label: 'CSS3' },
  { value: 'javascript', label: 'JavaScript' },
];

/** Human-readable name of a supported language (and of the `unknown` outcome). */
const LANGUAGE_LABELS: Readonly<Record<string, string>> = {
  python: 'Python',
  advpl: 'ADVPL',
  html: 'HTML5',
  css: 'CSS3',
  javascript: 'JavaScript',
  unknown: 'Desconhecida',
  auto: 'Detectar automaticamente',
};

/** Returns a readable PT-BR language name without ever exposing a raw token. */
export function languageLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === '') {
    return 'Não informada';
  }
  return LANGUAGE_LABELS[value.trim().toLowerCase()] ?? value.trim();
}

/** `true` when the language is one the backend can validate deterministically. */
export function isSupportedLanguage(value: string | null | undefined): value is LanguageId {
  if (value === null || value === undefined) {
    return false;
  }
  return LANGUAGE_OPTIONS.some((option) => option.value === value && option.value !== 'auto');
}
