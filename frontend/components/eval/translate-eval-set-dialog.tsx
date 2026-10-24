"use client";

import { Languages } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslateEvalSet } from "@/hooks/use-eval";
import { ENDONYMS, LANGUAGES, type Language } from "@/lib/i18n/languages";

const TARGETS = LANGUAGES.filter((language) => language !== "en");

/**
 * Ask for a translation of a ready English set. Rendered only for `eval.run` on such a
 * set; the route's own checks are the control. A language that already has a live
 * translation is shown disabled rather than hidden, so the list reads the same every time.
 */
export function TranslateEvalSetDialog({
  projectId,
  set,
  existing,
}: {
  projectId: string;
  set: { id: string; name: string };
  /** Languages this set already has a live translation into. */
  existing: Language[];
}) {
  const t = useTranslations("eval.translateDialog");
  const triggerLabel = useTranslations("eval.screen")("translate");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const firstFree = TARGETS.find((language) => !existing.includes(language)) ?? null;
  const [chosen, setChosen] = useState<Language | null>(null);
  // Until the user picks, follow the first free language, which may change as `existing` loads.
  const language = chosen ?? firstFree;
  const mutation = useTranslateEvalSet(projectId);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) mutation.reset();
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!language) return;
    mutation.mutate(
      { sourceSetId: set.id, language },
      {
        onSuccess: (created) => {
          toast.success(t("started"));
          setOpen(false);
          router.push(`/projects/${projectId}/eval/${created.id}`);
        },
      },
    );
  }

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Languages className="size-4" />
        {triggerLabel}
      </Button>
      <FormDialog
        open={open}
        onOpenChange={handleOpenChange}
        title={t("title", { name: set.name })}
        description={t("description")}
        submitLabel={t("submit")}
        isPending={mutation.isPending}
        error={mutation.error}
        onSubmit={handleSubmit}
      >
        <Field>
          <FieldLabel>{t("languageLabel")}</FieldLabel>
          <Select
            value={language ?? ""}
            onValueChange={(value) => setChosen((value || null) as Language | null)}
          >
            <SelectTrigger className="w-full" aria-label={t("languageAria")}>
              <SelectValue>
                {(value: string) => (value ? ENDONYMS[value as Language] : "")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {TARGETS.map((target) => {
                const taken = existing.includes(target);
                return (
                  <SelectItem key={target} value={target} disabled={taken}>
                    {taken
                      ? t("alreadyTranslated", { language: ENDONYMS[target] })
                      : ENDONYMS[target]}
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        </Field>
      </FormDialog>
    </>
  );
}
