/**
 * Timestamps are relative with an absolute `title` (`docs/design.md` → Lists):
 * "3 days ago", hover for the ISO value.
 */
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 60 * 60 * 1000],
  ["month", 30 * 24 * 60 * 60 * 1000],
  ["day", 24 * 60 * 60 * 1000],
  ["hour", 60 * 60 * 1000],
  ["minute", 60 * 1000],
];

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelative(iso: string): string {
  const elapsed = new Date(iso).getTime() - Date.now();
  for (const [unit, size] of UNITS) {
    if (Math.abs(elapsed) >= size) return relative.format(Math.round(elapsed / size), unit);
  }
  return "just now";
}

export function formatAbsolute(iso: string | null): string | undefined {
  return iso ? new Date(iso).toISOString() : undefined;
}
