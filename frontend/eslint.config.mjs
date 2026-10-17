import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import i18next from "eslint-plugin-i18next";

// Areas whose strings come from messages/*.json. Each migration task appends its
// directory; the last one replaces the list with the whole tree (plan Task 19).
const MIGRATED = [
  "components/profile/language-section.tsx",
  "components/auth/**/*.tsx",
  "components/form/**/*.tsx",
  "components/feedback/**/*.tsx",
];

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    files: MIGRATED,
    ignores: ["**/*.test.tsx", "components/ui/**"],
    plugins: { i18next },
    rules: {
      // JSX text and the attributes a user reads. Everything else (class names,
      // ids, hrefs) is not prose and is left alone.
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          "jsx-attributes": { include: ["aria-label", "placeholder", "title", "alt"] },
        },
      ],
    },
  },
]);

export default eslintConfig;
