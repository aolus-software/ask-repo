/**
 * "Chrome on macOS" from a user-agent string, for the profile's session list.
 *
 * Order matters in both tables. Edge and Opera carry "Chrome/", and Chrome carries
 * "Safari/", so the more specific name is tested first. An iPad's agent says
 * "Mac OS X" and Android's says "Linux", so iOS and Android come before them. A small
 * table instead of a dependency: this only has to tell a person's own devices apart,
 * and the raw string is always one hover away.
 */
const BROWSERS: [RegExp, string][] = [
  [/Edg\//, "Edge"],
  [/OPR\/|Opera/, "Opera"],
  [/Firefox\//, "Firefox"],
  [/Chrome\//, "Chrome"],
  [/Safari\//, "Safari"],
];

const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad|iPod/, "iOS"],
  [/Android/, "Android"],
  [/Windows/, "Windows"],
  [/CrOS/, "ChromeOS"],
  [/Mac OS X|Macintosh/, "macOS"],
  [/Linux/, "Linux"],
];

export function deviceLabel(userAgent: string | null): string {
  if (!userAgent?.trim()) return "Unknown device";
  const browser = BROWSERS.find(([pattern]) => pattern.test(userAgent))?.[1];
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent))?.[1];
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? userAgent;
}
