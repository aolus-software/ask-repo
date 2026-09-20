"use client";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";
import type { NotificationListParams, ProjectResponse } from "@/lib/api/types";
import { NOTIFICATION_TYPES } from "@/lib/notifications";

/**
 * "No filter" needs a real option value, the same sentinel every other list screen's
 * filter uses (see `AuditFilters`, `ModuleFilters`): a select whose item value is `""`
 * is indistinguishable from an unset one. It never leaves this file.
 */
const ANY = "any";

const ALL_TYPES = "All types";
const ALL_PROJECTS = "All projects";

/** "project.ready" -> "Project ready". Mirrors `auditEventLabel` in `lib/audit.ts`. */
function typeLabel(eventType: string): string {
  const words = eventType.replace(/[._]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function projectLabel(value: string, projects: ProjectResponse[]): string {
  if (value === ANY) return ALL_PROJECTS;
  return projects.find((project) => project.id === value)?.name ?? ALL_PROJECTS;
}

export function NotificationFilters({
  currentFilters,
  onFiltersChange,
}: {
  currentFilters: Partial<NotificationListParams>;
  onFiltersChange: (filters: Partial<NotificationListParams>) => void;
}) {
  // Matches `ModuleFilters`' cap — beyond a hundred projects this wants a searchable
  // combobox instead, which is why the value stays a plain id either way.
  const projectsQuery = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const projects = projectsQuery.data?.items ?? [];

  return (
    <>
      <div>
        <Select
          value={currentFilters.projectId ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              projectId: !value || value === ANY ? undefined : value,
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="Filter by project">
            {/* Base UI renders the raw value, not the chosen item's label, so an
                unset filter would read "any". Resolve it to the project's name. */}
            <SelectValue>{(value: string) => projectLabel(value, projects)}</SelectValue>
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

      <div>
        <Select
          value={currentFilters.eventType ?? ANY}
          onValueChange={(value: string | null | undefined) =>
            onFiltersChange({
              ...currentFilters,
              eventType: !value || value === ANY ? undefined : value,
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="Filter by type">
            <SelectValue>
              {(value: string) => (value === ANY ? ALL_TYPES : typeLabel(value))}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{ALL_TYPES}</SelectItem>
            {NOTIFICATION_TYPES.map((eventType) => (
              <SelectItem key={eventType} value={eventType}>
                {typeLabel(eventType)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <Checkbox
          id="unread-only"
          checked={Boolean(currentFilters.unreadOnly)}
          onCheckedChange={(checked) =>
            onFiltersChange({
              ...currentFilters,
              unreadOnly: checked === true ? true : undefined,
            })
          }
        />
        <label htmlFor="unread-only" className="text-sm text-foreground">
          Unread only
        </label>
      </div>
    </>
  );
}
