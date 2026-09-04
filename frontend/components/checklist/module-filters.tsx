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
import type { ProjectResponse } from "@/lib/api/types";

/**
 * "No filter" needs a real option value -- the same sentinel `ItemFilters` uses, and
 * for the same reason: a select whose item value is `""` is indistinguishable from an
 * unset select. It never leaves this file.
 */
const ANY = "any";

const ALL_PROJECTS = "All projects";

/** The label for a selected value: the sentinel reads as "no filter", not as "any". */
function labelFor(value: string, projects: ProjectResponse[]): string {
  if (value === ANY) return ALL_PROJECTS;
  return projects.find((project) => project.id === value)?.name ?? ALL_PROJECTS;
}

/**
 * The project filter for the module list.
 *
 * Every project is offered, not just the indexed ones. `CreateModuleDialog` filters to
 * `ready` because creating against anything else is a 409 the user cannot act on;
 * filtering is a read, and a module whose project has since gone back to indexing
 * still has rows worth finding.
 */
export function ModuleFilters({
  projectId,
  onProjectChange,
}: {
  projectId: string | undefined;
  onProjectChange: (projectId: string | undefined) => void;
}) {
  // Matches the create dialog's cap. Beyond a hundred projects this wants the
  // searchable combobox instead, which is why the value is a plain id either way.
  const query = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const projects = query.data?.items ?? [];

  return (
    // Wrapped so the control owns a whole toolbar grid cell, and `w-full` so the
    // trigger fills it -- `SelectTrigger` is `w-fit` by default, which collapses it
    // to the width of the shortest label.
    <div>
      <Select
        value={projectId ?? ANY}
        onValueChange={(value: string | null | undefined) =>
          onProjectChange(!value || value === ANY ? undefined : value)
        }
      >
        <SelectTrigger className="w-full" aria-label="Filter by project">
          {/* Base UI renders the raw value, not the chosen item's label, so an
              unset filter would read "any". Resolve it to the project's name. */}
          <SelectValue>{(value: string) => labelFor(value, projects)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{ALL_PROJECTS}</SelectItem>
          {projects.map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
