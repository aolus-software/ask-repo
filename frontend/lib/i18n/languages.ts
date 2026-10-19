/**
 * The languages AskRepo ships. Mirrors `backend/app/core/language.py`, and
 * `backend/tests/test_language_catalogue.py` fails when the two differ.
 */
export const LANGUAGES = ["en", "id", "ja", "ms", "zh-HK", "zh-TW", "ko"] as const;

export type Language = (typeof LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "en";

/** Each language in its own name, so a user finds theirs without reading the current one. */
export const ENDONYMS: Record<Language, string> = {
  en: "English",
  id: "Bahasa Indonesia",
  ja: "日本語",
  ms: "Bahasa Melayu",
  "zh-HK": "繁體中文（香港）",
  "zh-TW": "繁體中文（台灣）",
  ko: "한국어",
};

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

/**
 * Chinese tags that are not an exact match. Simplified (`zh`, `zh-CN`, `zh-Hans`, `zh-SG`)
 * is deliberately absent: showing a Simplified reader a Traditional catalogue is worse
 * than English.
 */
const CHINESE_ALIASES: Record<string, Language> = {
  "zh-mo": "zh-HK",
  "zh-hant": "zh-TW",
  "zh-hant-hk": "zh-HK",
  "zh-hant-mo": "zh-HK",
  "zh-hant-tw": "zh-TW",
};

function matchTag(tag: string): Language | undefined {
  const lower = tag.toLowerCase();
  const exact = LANGUAGES.find((code) => code.toLowerCase() === lower);
  if (exact) return exact;
  if (lower in CHINESE_ALIASES) return CHINESE_ALIASES[lower];
  const base = lower.split("-")[0];
  if (base === "zh") return undefined;
  return LANGUAGES.find((code) => code === base);
}

/** Accept-Language tags, highest q first; ties keep header order. */
function rankedTags(header: string): string[] {
  return header
    .split(",")
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.find((p) => p.trim().startsWith("q="));
      return { tag: tag.trim(), q: q ? Number(q.trim().slice(2)) : 1, index };
    })
    .filter(
      (entry) =>
        entry.tag && entry.tag !== "*" && !Number.isNaN(entry.q) && entry.q > 0,
    )
    .sort((a, b) => b.q - a.q || a.index - b.index)
    .map((entry) => entry.tag);
}

/**
 * The locale for one request: the `askrepo_locale` cookie (which mirrors the user
 * row), then `Accept-Language`, then English. Spec §2.2.
 */
export function resolveLocale(
  cookie: string | undefined,
  acceptLanguage: string | null,
): Language {
  if (isLanguage(cookie)) return cookie;
  for (const tag of rankedTags(acceptLanguage ?? "")) {
    const match = matchTag(tag);
    if (match) return match;
  }
  return DEFAULT_LANGUAGE;
}
