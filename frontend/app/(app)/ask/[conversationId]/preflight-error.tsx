"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useReindexProject } from "@/hooks/use-project-mutations";
import { useProject } from "@/hooks/use-projects";
import { isApiError } from "@/lib/api/errors";
import { PERMISSION, can } from "@/lib/can";
import { useErrorText } from "@/lib/i18n/error-text";

/**
 * Pre-flight failures arrive as ordinary HTTP errors before any body, so they render
 * in the conversation where the question was asked, not as a toast — they are about
 * this turn (design spec §9.8).
 *
 * Still mounted only when there IS an error, but the project query it needs for the
 * re-index button is no longer the reason: the screen now shows the project in its
 * header, so `useProject(projectId)` is already in cache by the time this renders and
 * this reads it rather than issuing a request.
 */
export function PreflightError({
  error,
  projectId,
}: {
  error: unknown;
  projectId: string;
}) {
  const t = useTranslations("ask");
  const errorText = useErrorText();
  const project = useProject(projectId);
  const reindex = useReindexProject(projectId);

  if (!isApiError(error)) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{t("preflight.couldNotAnswer")}</AlertTitle>
        <AlertDescription>{t("preflight.genericError")}</AlertDescription>
      </Alert>
    );
  }

  if (error.code === "EMBEDDING_MODEL_CHANGED") {
    const canManage = project.data
      ? can(project.data, PERMISSION.PROJECT_REINDEX)
      : false;
    return (
      <Alert variant="destructive">
        <AlertTitle>{t("preflight.needsReindexTitle")}</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>{t("preflight.needsReindexBody")}</p>
          {canManage ? (
            <Button
              size="sm"
              disabled={reindex.isPending}
              onClick={() =>
                reindex.mutate(undefined, {
                  onError: (e) => toast.error(errorText(e)),
                  onSuccess: (result) =>
                    toast.success(
                      result.enqueued
                        ? t("preflight.reindexStarted")
                        : t("preflight.reindexAlreadyRunning"),
                    ),
                })
              }
            >
              {t("preflight.reindexNow")}
            </Button>
          ) : (
            <p className="text-sm">{t("preflight.askToReindex")}</p>
          )}
        </AlertDescription>
      </Alert>
    );
  }

  if (error.code === "PROJECT_NOT_READY") {
    return (
      <Alert variant="info">
        <AlertTitle>{t("preflight.notReadyTitle")}</AlertTitle>
        <AlertDescription>{t("preflight.notReadyBody")}</AlertDescription>
      </Alert>
    );
  }

  return (
    <Alert variant="destructive">
      <AlertTitle>{t("preflight.couldNotAnswer")}</AlertTitle>
      <AlertDescription>{errorText(error)}</AlertDescription>
    </Alert>
  );
}
