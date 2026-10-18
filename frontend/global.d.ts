import type { Language } from "./lib/i18n/languages";
import type en from "./messages/en/index";

declare module "next-intl" {
  interface AppConfig {
    Locale: Language;
    Messages: typeof en;
  }
}
