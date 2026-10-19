import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { LANGUAGES } from "@/lib/i18n/languages";

type Tree = { [key: string]: string | Tree };

const ROOT = join(__dirname, "../../messages");

/** One locale's namespaces, keyed by file name; `_meta.json` is not a namespace. */
function load(locale: string): Tree {
  const tree: Tree = {};
  for (const file of readdirSync(join(ROOT, locale))) {
    if (!file.endsWith(".json") || file === "_meta.json") continue;
    tree[file.slice(0, -".json".length)] = JSON.parse(
      readFileSync(join(ROOT, locale, file), "utf8"),
    );
  }
  return tree;
}

function meta(locale: string): unknown {
  return JSON.parse(readFileSync(join(ROOT, locale, "_meta.json"), "utf8"));
}

function leaves(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    if (key === "_meta") continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else for (const [k, v] of leaves(value, path)) out.set(k, v);
  }
  return out;
}

/** ICU argument names in a message: `{count}`, `{count, plural, …}`, `<link>`. */
function placeholders(message: string): string[] {
  const args = [...message.matchAll(/\{\s*([A-Za-z0-9_]+)\s*[,}]/g)].map((m) => m[1]);
  const tags = [...message.matchAll(/<([A-Za-z0-9_]+)>/g)].map((m) => `<${m[1]}>`);
  return [...new Set([...args, ...tags])].sort();
}

const english = leaves(load("en"));

describe.each(LANGUAGES.filter((l) => l !== "en"))("messages/%s", (locale) => {
  const translated = () => leaves(load(locale));

  it("has exactly the English keys", () => {
    expect([...translated().keys()].sort()).toEqual([...english.keys()].sort());
  });

  it("keeps every placeholder and tag", () => {
    const messages = translated();
    for (const [key, message] of english) {
      expect(placeholders(messages.get(key) ?? ""), key).toEqual(placeholders(message));
    }
  });

  it("declares whether a native speaker has reviewed it", () => {
    expect(meta(locale)).toEqual({ reviewed: false });
  });

  it("imports exactly the English namespaces in its index", () => {
    const index = readFileSync(join(ROOT, locale, "index.ts"), "utf8");
    const source = readFileSync(join(ROOT, "en", "index.ts"), "utf8");
    expect(index.replace(/\/\*\*[\s\S]*?\*\//, "")).toEqual(
      source.replace(/\/\*\*[\s\S]*?\*\//, ""),
    );
  });
});
