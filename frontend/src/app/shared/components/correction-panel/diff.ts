/** One line of a unified diff, already classified for presentation. */
export type DiffLineKind = 'add' | 'remove' | 'context' | 'hunk' | 'meta';

export interface DiffLine {
  readonly kind: DiffLineKind;
  readonly sign: string;
  readonly text: string;
}

/**
 * Splits a unified diff into lines and classifies them.
 *
 * The UI renders one element per line with Angular interpolation, so user
 * content is always escaped; this parser never produces HTML.
 */
export function parseUnifiedDiff(diff: string): readonly DiffLine[] {
  const normalized = diff.replace(/\r\n?/g, '\n');
  if (normalized === '') {
    return [];
  }

  const rawLines = normalized.split('\n');
  if (rawLines[rawLines.length - 1] === '') {
    rawLines.pop();
  }

  return rawLines.map((line) => {
    if (line.startsWith('@@')) {
      return { kind: 'hunk', sign: '@@', text: line };
    }
    if (
      line.startsWith('--- ') ||
      line.startsWith('+++ ') ||
      line.startsWith('diff ') ||
      line.startsWith('index ') ||
      line.startsWith('\\ No newline')
    ) {
      return { kind: 'meta', sign: '', text: line };
    }
    if (line.startsWith('+')) {
      return { kind: 'add', sign: '+', text: line.slice(1) };
    }
    if (line.startsWith('-')) {
      return { kind: 'remove', sign: '-', text: line.slice(1) };
    }
    return { kind: 'context', sign: ' ', text: line.startsWith(' ') ? line.slice(1) : line };
  });
}
