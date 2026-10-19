"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { ProjectStatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ProjectResponse } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

/** Column order is fixed by `docs/design.md`: identity, status, timestamps, actions. */
export function ProjectTable({
  projects,
  isLoading,
  rowActions,
}: {
  projects: ProjectResponse[];
  isLoading: boolean;
  rowActions: (project: ProjectResponse) => React.ReactNode;
}) {
  const t = useTranslations("projects.table");
  const formatRelative = useFormatRelative();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("columns.name")}</TableHead>
          <TableHead>{t("columns.repository")}</TableHead>
          <TableHead>{t("columns.status")}</TableHead>
          <TableHead>{t("columns.indexed")}</TableHead>
          <TableHead>{t("columns.commit")}</TableHead>
          <TableHead>{t("columns.updated")}</TableHead>
          <TableHead className="text-right">{t("columns.actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading ? (
          <TableSkeleton columns={7} />
        ) : (
          projects.map((project) => (
            <TableRow key={project.id}>
              <TableCell className="font-medium">
                <Link href={`/projects/${project.id}`} className="hover:text-primary">
                  {project.name}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground font-mono text-sm">
                {project.repoUrl.replace(/^https:\/\//, "")}
                <span className="text-muted-foreground/70"> @{project.branch}</span>
              </TableCell>
              <TableCell>
                <ProjectStatusBadge status={project.status} />
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {project.fileCount === null
                  ? "—"
                  : t("indexedCounts", {
                      files: project.fileCount,
                      chunks: project.chunkCount ?? 0,
                    })}
              </TableCell>
              <TableCell className="font-mono text-sm">
                {project.lastIndexedCommit
                  ? project.lastIndexedCommit.slice(0, 7)
                  : "—"}
              </TableCell>
              <TableCell title={formatAbsolute(project.updatedAt)}>
                {formatRelative(project.updatedAt)}
              </TableCell>
              <TableCell className="text-right">{rowActions(project)}</TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
