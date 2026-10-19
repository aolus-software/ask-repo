"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { ListError } from "@/components/feedback/list-error";
import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { useAnswerStyle, useUpdateAnswerStyle } from "@/hooks/use-profile";
import type { AnswerStyle } from "@/lib/api/types";

/** `Default` is the empty string in the radio group and `null` on the wire. */
const DEFAULT = "";

const DIALS = [
  {
    key: "detail",
    options: ["brief", "thorough"],
  },
  {
    key: "familiarity",
    options: ["new", "expert"],
  },
  {
    key: "format",
    options: ["prose", "bullets"],
  },
] as const;

type DialOption = (typeof DIALS)[number]["options"][number];

const UNSET: AnswerStyle = { detail: null, familiarity: null, format: null };

/**
 * Three dials that shape the caller's own Ask answers. Every sentence they add to the
 * prompt is fixed by the project -- there is no free text -- and they never reach the
 * QA Checklist or Mock Data, which a project shares. Rendered inside the profile's
 * Answer style tab, which supplies the heading.
 */
export function AnswerStyleSection() {
  const t = useTranslations("profile.answerStyle");
  const [draft, setDraft] = useState<AnswerStyle | null>(null);
  const query = useAnswerStyle();
  const save = useUpdateAnswerStyle();
  const style = draft ?? query.data ?? UNSET;
  // Until the stored style arrives the radios would show Default; one click would then
  // save null for the other two dials and overwrite what is stored.
  const loaded = query.data !== undefined;

  if (query.isError) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  return (
    <div>
      <p className="text-muted-foreground mb-4 text-sm">{t("intro")}</p>

      <Card className="gap-6 p-6">
        {DIALS.map((dial) =>
          !loaded ? (
            // Same shape as a settled dial (label, then one row of options) so nothing
            // jumps, and no radio claims a value that has not arrived.
            <div key={dial.key} className="grid gap-2">
              <Skeleton className="h-4 w-20" />
              <div className="flex flex-wrap gap-4">
                {Array.from({ length: dial.options.length + 1 }, (_, index) => (
                  <Skeleton key={index} className="h-5 w-24" />
                ))}
              </div>
            </div>
          ) : (
            <div key={dial.key} className="grid gap-2">
              <Label id={`answer-style-${dial.key}`}>{t(`dials.${dial.key}`)}</Label>
              <RadioGroup
                aria-labelledby={`answer-style-${dial.key}`}
                value={style[dial.key] ?? DEFAULT}
                onValueChange={(value) =>
                  setDraft({ ...style, [dial.key]: value === DEFAULT ? null : value })
                }
                className="flex flex-wrap gap-4"
              >
                {[DEFAULT, ...dial.options].map((value) => (
                  <Label
                    key={value}
                    className="text-foreground flex items-center gap-2 text-sm font-normal"
                  >
                    <RadioGroupItem value={value} />
                    {value === DEFAULT
                      ? t("default")
                      : t(`options.${value as DialOption}`)}
                  </Label>
                ))}
              </RadioGroup>
            </div>
          ),
        )}
      </Card>

      {/* No field the backend can name is user-typed, so a failure is form-level
          (`forms.md` §4). */}
      <FormError error={save.error} />

      <div className="mt-4 flex justify-end">
        <Button
          disabled={draft === null || save.isPending || !loaded}
          onClick={() =>
            save.mutate(style, {
              onSuccess: () => {
                toast.success(t("saved"));
                setDraft(null);
              },
            })
          }
        >
          {t("save")}
        </Button>
      </div>
    </div>
  );
}
