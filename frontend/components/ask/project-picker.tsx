"use client";

import { useMemo } from "react";

import { StatusBadge } from "@/components/feedback/status-badge";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";
import type { ProjectResponse } from "@/lib/api/types";

/**
 * Pick the project a question is asked against.
 *
 * A combobox rather than a select because the list is instance-wide and unbounded —
 * typing to narrow is the only thing that scales past a couple of dozen repositories.
 *
 * Only a `ready` project can be asked: anything else answers 409 PROJECT_NOT_READY.
 * Non-ready projects stay in the list, disabled and badged with their status, rather
 * than being hidden — an operator who just added a repository needs to see it
 * indexing, not conclude it vanished. If every project is disabled that is the honest
 * picture: nothing is queryable yet.
 *
 * `GET /projects` has no status filter (design spec §2.6), so this fetches a page of
 * 100 by recency and filters client-side. Beyond 100 the list is incomplete — the
 * combobox's own text filter is what makes that bearable.
 */
export function ProjectPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (projectId: string) => void;
}) {
  const query = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });

  const projects = useMemo(() => query.data?.items ?? [], [query.data]);
  const selected = projects.find((project) => project.id === value) ?? null;

  return (
    <Combobox
      items={projects}
      value={selected}
      onValueChange={(next: ProjectResponse | null) => {
        if (next) onChange(next.id);
      }}
      itemToStringLabel={(project: ProjectResponse) => project.name}
    >
      <ComboboxInput
        className="w-full max-w-sm"
        placeholder={query.isLoading ? "Loading projects…" : "Search projects"}
        aria-label="Project"
      />
      <ComboboxContent>
        <ComboboxEmpty>
          {query.isLoading ? "Loading…" : "No project matches."}
        </ComboboxEmpty>
        <ComboboxList>
          {(project: ProjectResponse) => (
            <ComboboxItem
              key={project.id}
              value={project}
              disabled={project.status !== "ready"}
              className="justify-between"
            >
              <span className="truncate">{project.name}</span>
              {project.status === "ready" ? null : (
                <StatusBadge status={project.status} />
              )}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
