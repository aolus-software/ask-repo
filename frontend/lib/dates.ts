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

const formatters = new Map<string, Intl.RelativeTimeFormat>();

function relativeFormat(locale: string): Intl.RelativeTimeFormat {
  let formatter = formatters.get(locale);
  if (!formatter) {
    formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    formatters.set(locale, formatter);
  }
  return formatter;
}

/** "3 days ago" in the given locale; `now` is injectable so tests are deterministic. */
export function formatRelative(
  iso: string,
  locale: string,
  now: number = Date.now(),
): string {
  const elapsed = new Date(iso).getTime() - now;
  const relative = relativeFormat(locale);
  for (const [unit, size] of UNITS) {
    if (Math.abs(elapsed) >= size)
      return relative.format(Math.round(elapsed / size), unit);
  }
  // `numeric: "auto"` renders 0 seconds as the locale's own word for now.
  return relative.format(0, "second");
}

export function formatAbsolute(iso: string | null): string | undefined {
  return iso ? new Date(iso).toISOString() : undefined;
}

/**
 * A bare calendar day (`YYYY-MM-DD`, no time component) rendered for display.
 * `Date.parse` on a date-only ISO string is UTC midnight, so this reads the
 * `YYYY-MM-DD` segment back out directly rather than routing through a `Date` and
 * risking the browser's local timezone shifting it to the adjacent day.
 */
export function formatDay(isoDate: string, locale?: string): string {
  const day = isoDate.slice(0, 10);
  if (!locale) return day;
  // Pinned to UTC for the same reason: the day must not move with the viewer's zone.
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}
