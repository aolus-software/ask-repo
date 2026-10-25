"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ENDONYMS, isLanguage, LANGUAGES } from "@/lib/i18n/languages";

/**
 * The language choice for a signed-out visitor. There is no user row to store it on,
 * so it is written to the locale cookie only (`POST /api/auth/locale`).
 */
export function LocaleSelect() {
  const t = useTranslations("auth.locale");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();

  // No success toast: the page re-renders in the new language, which is the confirmation.
  async function change(language: string | null) {
    if (!isLanguage(language)) return;
    try {
      const res = await fetch("/api/auth/locale", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ language }),
      });
      if (!res.ok) {
        toast.error(tErrors("generic"));
        return;
      }
    } catch {
      toast.error(tErrors("generic"));
      return;
    }
    router.refresh();
  }

  return (
    <Select value={locale} onValueChange={change}>
      <SelectTrigger size="sm" aria-label={t("label")}>
        <SelectValue>
          {(value: string) => (isLanguage(value) ? ENDONYMS[value] : value)}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {LANGUAGES.map((code) => (
          <SelectItem key={code} value={code} lang={code}>
            {ENDONYMS[code]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
