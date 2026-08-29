"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/feedback/status-badge";
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
import { formatAbsolute, formatRelative } from "@/lib/dates";

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
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Repository</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Indexed</TableHead>
          <TableHead>Commit</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="text-right">Actions</TableHead>
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
                <StatusBadge status={project.status} />
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {project.fileCount === null
                  ? "—"
                  : `${project.fileCount} files · ${project.chunkCount ?? 0} chunks`}
              </TableCell>
              <TableCell className="font-mono text-sm">
                {project.lastIndexedCommit ? project.lastIndexedCommit.slice(0, 7) : "—"}
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
