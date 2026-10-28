/**
 * Client-side text download.
 *
 * The correction is already in memory, so exporting never needs a second
 * request and works for anonymous corrections too (the server-side export
 * endpoint is owner-scoped).
 */
export function downloadText(
  content: string,
  filename: string,
  mimeType = 'text/plain;charset=utf-8',
): boolean {
  if (typeof document === 'undefined' || typeof Blob === 'undefined') {
    return false;
  }
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
    return false;
  }

  const href = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';

  try {
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    // Revoking synchronously can cancel the download in some browsers.
    setTimeout(() => {
      if (typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(href);
      }
    }, 0);
  }
  return true;
}

/** File name for the corrected download, keeping the original extension. */
export function correctedFilename(file: string | null, id: string): string {
  const base = safeBaseName(file) ?? `correcao-${shortId(id)}`;
  const dot = base.lastIndexOf('.');
  if (dot > 0) {
    return `${base.slice(0, dot)}.corrected${base.slice(dot)}`;
  }
  return `${base}.corrected.txt`;
}

/** File name for the unified diff download. */
export function diffFilename(file: string | null, id: string): string {
  const base = safeBaseName(file) ?? `correcao-${shortId(id)}`;
  const dot = base.lastIndexOf('.');
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return `${stem}.diff.txt`;
}

function safeBaseName(file: string | null): string | null {
  if (file === null) {
    return null;
  }
  const segment = file.replace(/\\/g, '/').split('/').pop()?.trim() ?? '';
  if (segment === '' || segment === '.' || segment === '..') {
    return null;
  }
  return segment.replace(/[^\w.-]+/g, '_').slice(0, 120);
}

function shortId(id: string): string {
  const clean = id.replace(/[^\w-]+/g, '').slice(0, 8);
  return clean === '' ? 'ia' : clean;
}
