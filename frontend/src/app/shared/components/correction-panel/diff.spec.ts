import { describe, expect, it } from 'vitest';

import { parseUnifiedDiff } from './diff';

describe('parseUnifiedDiff', () => {
  it('classifies headers, hunks, removals, additions and context lines', () => {
    const diff = [
      '--- a/src/app.py',
      '+++ b/src/app.py',
      '@@ -1,3 +1,3 @@',
      '-value = 1',
      '+value = 2',
      ' unchanged',
      '\\ No newline at end of file',
    ].join('\n');

    expect(parseUnifiedDiff(diff)).toEqual([
      { kind: 'meta', sign: '', text: '--- a/src/app.py' },
      { kind: 'meta', sign: '', text: '+++ b/src/app.py' },
      { kind: 'hunk', sign: '@@', text: '@@ -1,3 +1,3 @@' },
      { kind: 'remove', sign: '-', text: 'value = 1' },
      { kind: 'add', sign: '+', text: 'value = 2' },
      { kind: 'context', sign: ' ', text: 'unchanged' },
      { kind: 'meta', sign: '', text: '\\ No newline at end of file' },
    ]);
  });

  it('keeps addition markers inside content and accepts CRLF', () => {
    const parsed = parseUnifiedDiff('--- a\r\n+++ b\r\n+x = "+"\r\n');

    expect(parsed.map((line) => line.kind)).toEqual(['meta', 'meta', 'add']);
    expect(parsed[2]?.text).toBe('x = "+"');
  });

  it('returns an empty list for an empty diff', () => {
    expect(parseUnifiedDiff('')).toEqual([]);
  });
});
