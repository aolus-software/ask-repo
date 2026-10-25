"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ListError } from "@/components/feedback/list-error";
import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { useLanguage, useUpdateLanguage } from "@/hooks/use-profile";
import { ENDONYMS, isLanguage, LANGUAGES, type Language } from "@/lib/i18n/languages";

/** "Browser default" is the empty string in the radio group and `null` on the wire. */
const BROWSER_DEFAULT = "";

/**
 * The caller's interface language. Endonyms are not in the catalogue: a language's own
 * name is the same in every interface. Rendered inside the profile's Language tab,
 * which supplies the heading.
 */
export function LanguageSection() {
  const t = useTranslations("profile.language");
  const router = useRouter();
  const [draft, setDraft] = useState<Language | null | undefined>(undefined);
  const query = useLanguage();
  const save = useUpdateLanguage();
  const loaded = query.data !== undefined;
  const value = draft !== undefined ? draft : (query.data?.language ?? null);

  if (query.isError) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  return (
    <div>
      <p className="text-muted-foreground mb-4 text-sm">{t("intro")}</p>

      <Card className="gap-4 p-6">
        {!loaded ? (
          <div className="grid gap-3">
            {Array.from({ length: LANGUAGES.length + 1 }, (_, index) => (
              <Skeleton key={index} className="h-5 w-40" />
            ))}
          </div>
        ) : (
          <RadioGroup
            aria-label={t("groupAria")}
            value={value ?? BROWSER_DEFAULT}
            onValueChange={(next) => setDraft(isLanguage(next) ? next : null)}
            className="grid gap-3"
          >
            <Label className="text-foreground flex items-center gap-2 text-sm font-normal">
              <RadioGroupItem value={BROWSER_DEFAULT} />
              {t("browserDefault")}
            </Label>
            {LANGUAGES.map((code) => (
              <Label
                key={code}
                lang={code}
                className="text-foreground flex items-center gap-2 text-sm font-normal"
              >
                <RadioGroupItem value={code} />
                {ENDONYMS[code]}
              </Label>
            ))}
          </RadioGroup>
        )}
      </Card>

      <FormError error={save.error} />

      <div className="mt-4 flex justify-end">
        <Button
          disabled={draft === undefined || save.isPending || !loaded}
          onClick={() =>
            save.mutate(
              { language: value },
              {
                onSuccess: () => {
                  toast.success(t("saved"));
                  setDraft(undefined);
                  router.refresh();
                },
              },
            )
          }
        >
          {t("save")}
        </Button>
      </div>
    </div>
  );
}
