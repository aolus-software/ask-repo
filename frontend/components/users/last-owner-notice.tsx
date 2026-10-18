"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { Fragment } from "react";

import { Alert } from "@/components/ui/alert";
import { ApiError } from "@/lib/api/errors";

interface BlockingProject {
  id: string;
  name: string;
}

/**
 * The `409 LAST_OWNER` refusal, rendered as the projects that are blocking rather
 * than as a generic banner. "No" is not actionable; "no, because these three
 * projects would have no owner" is — and each name links to where it gets fixed.
 *
 * The names are joined by the locale's own list format ("a, b, and c"), and they are
 * rendered as written: a project name is the admin's, not ours to translate.
 */
export function LastOwnerNotice({ error }: { error: unknown }) {
  const t = useTranslations("settings.users");
  const locale = useLocale();

  if (!(error instanceof ApiError) || error.code !== "LAST_OWNER") return null;

  const projects = (error.extra.projects ?? []) as BlockingProject[];
  const byName = new Map(projects.map((project) => [project.name, project]));
  const parts = new Intl.ListFormat(locale, { type: "conjunction" }).formatToParts(
    projects.map((project) => project.name),
  );

  const message = t.rich("lastOwner", {
    projects: () =>
      parts.map((part, index) => {
        const project = part.type === "element" ? byName.get(part.value) : null;
        return (
          <Fragment key={index}>
            {project ? (
              <Link href={`/projects/${project.id}`} className="underline">
                {project.name}
              </Link>
            ) : (
              part.value
            )}
          </Fragment>
        );
      }),
  });

  return (
    <Alert role="alert" className="bg-card text-card-foreground border-border">
      <p className="text-sm">{message}</p>
    </Alert>
  );
}
