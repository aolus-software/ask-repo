"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/form/form-error";
import { LanguageSelect } from "@/components/projects/language-select";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useUpdateProjectContentLanguage } from "@/hooks/use-project-mutations";
import type { ProjectResponse } from "@/lib/api/types";
import { can, PERMISSION } from "@/lib/can";
import { ENDONYMS, type Language } from "@/lib/i18n/languages";

/**
 * The language this project's generated content (checklists, mock data, refinement
 * chats, exports) is written in. Editable with `project.update`; otherwise read-only.
 */
export function ContentLanguageSection({ project }: { project: ProjectResponse }) {
  const t = useTranslations("projects.contentLanguage");
  const [draft, setDraft] = useState<Language | undefined>(undefined);
  const mutation = useUpdateProjectContentLanguage(project.id);
  const value = draft ?? project.contentLanguage;
  const editable = can(project, PERMISSION.PROJECT_UPDATE);

  return (
    <Card className="gap-3 p-6">
      <div>
        <h2 className="text-foreground text-base font-semibold">{t("title")}</h2>
        <p className="text-muted-foreground text-sm">{t("description")}</p>
      </div>

      {editable ? (
        <>
          <div className="max-w-xs">
            <LanguageSelect value={value} onChange={setDraft} ariaLabel={t("title")} />
          </div>
          <FormError error={mutation.error} />
          <div>
            <Button
              disabled={mutation.isPending || value === project.contentLanguage}
              onClick={() =>
                mutation.mutate(value, {
                  onSuccess: () => {
                    toast.success(t("saved"));
                    setDraft(undefined);
                  },
                })
              }
            >
              {t("save")}
            </Button>
          </div>
        </>
      ) : (
        <p className="text-foreground text-sm" lang={project.contentLanguage}>
          {t("current", { language: ENDONYMS[project.contentLanguage] })}
        </p>
      )}
    </Card>
  );
}
