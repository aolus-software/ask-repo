import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import i18next from "eslint-plugin-i18next";

// Every screen's strings come from messages/<locale>/; tests and the CLI-managed
// shadcn components are excluded below (plan Task 19).
const TRANSLATED = ["app/**/*.tsx", "components/**/*.tsx"];

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
    files: TRANSLATED,
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
