/**
 * Saving a fetched file. Used where a download is fetched rather than linked, so an
 * error response can be shown in the form instead of replacing the page.
 */

const FALLBACK_FILENAME = "export";

/**
 * The `filename="..."` of a `Content-Disposition` header, or a fallback. The backend
 * sends fixed ASCII names, so the quoted form is the only one read.
 */
export function filenameFromDisposition(header: string | null): string {
  const match = header ? /filename="([^"]+)"/.exec(header) : null;
  return match?.[1] ?? FALLBACK_FILENAME;
}

/** Hand a blob to the browser as a download, then release its object URL. */
export function saveDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
