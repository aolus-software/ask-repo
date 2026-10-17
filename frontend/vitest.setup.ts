import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import en from "@/messages/en/index";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// Components read their strings through next-intl. Tests render them without the
// root layout's provider, so the hooks are backed by the real translator over the
// English catalogue: a test asserts the same English the app shows, and a missing
// key throws exactly as it would in the app.
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  return {
    ...actual,
    useLocale: () => "en",
    useTranslations: (namespace?: string) =>
      actual.createTranslator({
        locale: "en",
        messages: en,
        namespace: namespace as never,
      }),
    useFormatter: () => actual.createFormatter({ locale: "en" }),
  };
});

vi.mock("next-intl/server", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl/server")>();
  const intl = await import("next-intl");
  return {
    ...actual,
    getLocale: async () => "en",
    getTranslations: async (namespace?: string) =>
      intl.createTranslator({
        locale: "en",
        messages: en,
        namespace: namespace as never,
      }),
  };
});
