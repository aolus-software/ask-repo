"use client";

import { useState } from "react";
import { toast } from "sonner";

import { ListError } from "@/components/feedback/list-error";
import { FormError } from "@/components/form/form-error";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useAnswerStyle, useUpdateAnswerStyle } from "@/hooks/use-profile";
import type { AnswerStyle } from "@/lib/api/types";

/** `Default` is the empty string in the radio group and `null` on the wire. */
const DEFAULT = "";

const DIALS = [
  {
    key: "detail",
    label: "Detail",
    options: [
      { value: "brief", label: "Brief" },
      { value: "thorough", label: "Thorough" },
    ],
  },
  {
    key: "familiarity",
    label: "Familiarity",
    options: [
      { value: "new", label: "New to this repository" },
      { value: "expert", label: "Expert" },
    ],
  },
  {
    key: "format",
    label: "Format",
    options: [
      { value: "prose", label: "Prose" },
      { value: "bullets", label: "Bullets" },
    ],
  },
] as const;

const UNSET: AnswerStyle = { detail: null, familiarity: null, format: null };

/**
 * Three dials that shape the caller's own Ask answers. Every sentence they add to the
 * prompt is fixed by the project -- there is no free text -- and they never reach the
 * QA Checklist or Mock Data, which a project shares. Rendered inside the profile's
 * Answer style tab, which supplies the heading.
 */
export function AnswerStyleSection() {
  const [draft, setDraft] = useState<AnswerStyle | null>(null);
  const query = useAnswerStyle();
  const save = useUpdateAnswerStyle();
  const style = draft ?? query.data ?? UNSET;

  if (query.isError) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  return (
    <div>
      <p className="text-muted-foreground mb-4 text-sm">
        Shapes the answers you get on Ask. It never changes the QA Checklist or Mock
        Data, which your whole team shares.
      </p>

      <Card className="gap-6 p-6">
        {DIALS.map((dial) => (
          <div key={dial.key} className="grid gap-2">
            <Label id={`answer-style-${dial.key}`}>{dial.label}</Label>
            <RadioGroup
              aria-labelledby={`answer-style-${dial.key}`}
              value={style[dial.key] ?? DEFAULT}
              onValueChange={(value) =>
                setDraft({ ...style, [dial.key]: value === DEFAULT ? null : value })
              }
              className="flex flex-wrap gap-4"
            >
              {[{ value: DEFAULT, label: "Default" }, ...dial.options].map((option) => (
                <Label
                  key={option.value}
                  className="text-foreground flex items-center gap-2 text-sm font-normal"
                >
                  <RadioGroupItem value={option.value} />
                  {option.label}
                </Label>
              ))}
            </RadioGroup>
          </div>
        ))}
      </Card>

      {/* No field the backend can name is user-typed, so a failure is form-level
          (`forms.md` §4). */}
      <FormError error={save.error} />

      <div className="mt-4 flex justify-end">
        <Button
          disabled={draft === null || save.isPending}
          onClick={() =>
            save.mutate(style, {
              onSuccess: () => {
                toast.success("Answer style saved");
                setDraft(null);
              },
            })
          }
        >
          Save answer style
        </Button>
      </div>
    </div>
  );
}
