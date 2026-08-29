"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";
import { statusLabel } from "@/lib/status";

/**
 * Only `ready` projects can be asked — anything else answers 409 PROJECT_NOT_READY.
 *
 * GET /projects has no status filter (design spec §2.6), so this fetches a page of
 * 100 by recency and filters client-side. Non-ready projects are shown DISABLED and
 * labelled with their status rather than hidden: an operator who just added a
 * repository should see it indexing, not conclude it vanished.
 *
 * Known limit: beyond 100 projects the list is incomplete. Search narrows it.
 */
export function ProjectPicker({
  value,
  onChange,
  search,
}: {
  value: string | null;
  onChange: (projectId: string) => void;
  search?: string;
}) {
  const query = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
    search: search || undefined,
  });
  const projects = query.data?.items ?? [];

  return (
    // Base UI hands back `string | null`; the picker only ever reports a real
    // selection upward, so a null clear is ignored rather than widening onChange.
    <Select
      value={value ?? undefined}
      onValueChange={(next) => {
        if (next) onChange(next);
      }}
    >
      <SelectTrigger className="w-full max-w-sm" aria-label="Project">
        <SelectValue placeholder={query.isLoading ? "Loading projects…" : "Choose a project"} />
      </SelectTrigger>
      <SelectContent>
        {projects.map((project) => (
          <SelectItem key={project.id} value={project.id} disabled={project.status !== "ready"}>
            {project.name}
            {project.status === "ready" ? "" : ` · ${statusLabel(project.status)}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
