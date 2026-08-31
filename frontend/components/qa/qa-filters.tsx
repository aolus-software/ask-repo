"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProjects } from "@/hooks/use-projects";
import { useUsers } from "@/hooks/use-users";
import { apiFetch } from "@/lib/api/client";
import { SORT, endpoints } from "@/lib/api/endpoints";
import type { QAListParams, QASource, QAStatus } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";
import { qaStatusLabel } from "@/lib/status";

/** The sentinel a `Select` uses for "no filter" — `QAListParams` fields are optional,
 * but Base UI's `Select` needs a real, stable string to control against. */
const ALL = "all";

const SOURCES: QASource[] = ["manual", "generated"];
const SOURCE_LABELS: Record<QASource, string> = {
  manual: "Manual",
  generated: "Generated",
};

const STATUSES: QAStatus[] = ["unreviewed", "pass", "fail"];

/**
 * Debounced so typing a module name does not fire a request per keystroke, mirroring
 * `ListToolbar`'s own search debounce.
 */
function ModuleFilter({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (draft === value) return;
    const timer = setTimeout(() => onChange(draft), 300);
    return () => clearTimeout(timer);
  }, [draft, value, onChange]);

  return (
    <Input
      placeholder="Module"
      aria-label="Filter by module"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
    />
  );
}

/**
 * The six QA List filters — project, module, tag, source, status, creator. Every
 * control reports a patch through the single `onChange`; the screen is the one place
 * that owns `QAListParams`, exactly as `.claude/rules/forms.md` requires for a field's
 * value to have one write path.
 *
 * Each `Select` fetches its own options, the same way `ProjectPicker` and
 * `conversation-rail`'s project combobox do — a widget owns the data it renders.
 * `useProjects`/`useUsers` here use the same params as any other caller, so React
 * Query's cache key matches theirs and no second network request happens.
 */
export function QAFilters({
  params,
  onChange,
}: {
  params: QAListParams;
  onChange: (patch: Partial<QAListParams>) => void;
}) {
  const projects = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const users = useUsers({ limit: 100, sort: SORT.users.name, sortDirection: "asc" });
  const tags = useQuery({
    queryKey: keys.qaPairs.tags,
    queryFn: () => apiFetch<string[]>(endpoints.qaPairs.tags),
  });

  const projectNameById = useMemo(
    () =>
      new Map(
        (projects.data?.items ?? []).map((project) => [project.id, project.name]),
      ),
    [projects.data],
  );
  const userNameById = useMemo(
    () => new Map((users.data?.items ?? []).map((user) => [user.id, user.name])),
    [users.data],
  );

  return (
    <>
      <Select
        value={params.projectId ?? ALL}
        onValueChange={(value) =>
          onChange({ projectId: value && value !== ALL ? value : undefined })
        }
      >
        <SelectTrigger aria-label="Filter by project" className="w-full">
          <SelectValue placeholder="All projects">
            {(value: string) =>
              value === ALL ? "All projects" : (projectNameById.get(value) ?? value)
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All projects</SelectItem>
          {(projects.data?.items ?? []).map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <ModuleFilter
        value={params.module ?? ""}
        onChange={(value) => onChange({ module: value || undefined })}
      />

      <Combobox
        items={tags.data ?? []}
        value={params.tag ?? null}
        onValueChange={(next: string | null) => onChange({ tag: next ?? undefined })}
      >
        <ComboboxInput
          className="w-full"
          showClear
          placeholder={tags.isLoading ? "Loading tags…" : "Filter by tag"}
          aria-label="Filter by tag"
        />
        <ComboboxContent>
          <ComboboxEmpty>
            {tags.isLoading ? "Loading…" : "No tag matches."}
          </ComboboxEmpty>
          <ComboboxList>
            {(tag: string) => (
              <ComboboxItem key={tag} value={tag}>
                {tag}
              </ComboboxItem>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>

      <Select
        value={params.source ?? ALL}
        onValueChange={(value) =>
          onChange({ source: value && value !== ALL ? (value as QASource) : undefined })
        }
      >
        <SelectTrigger aria-label="Filter by source" className="w-full">
          <SelectValue placeholder="All sources">
            {(value: string) =>
              value === ALL ? "All sources" : SOURCE_LABELS[value as QASource]
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All sources</SelectItem>
          {SOURCES.map((source) => (
            <SelectItem key={source} value={source}>
              {SOURCE_LABELS[source]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={params.status ?? ALL}
        onValueChange={(value) =>
          onChange({ status: value && value !== ALL ? (value as QAStatus) : undefined })
        }
      >
        <SelectTrigger aria-label="Filter by status" className="w-full">
          <SelectValue placeholder="All statuses">
            {(value: string) =>
              value === ALL ? "All statuses" : qaStatusLabel(value as QAStatus)
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All statuses</SelectItem>
          {STATUSES.map((status) => (
            <SelectItem key={status} value={status}>
              {qaStatusLabel(status)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={params.createdBy ?? ALL}
        onValueChange={(value) =>
          onChange({ createdBy: value && value !== ALL ? value : undefined })
        }
      >
        <SelectTrigger aria-label="Filter by creator" className="w-full">
          <SelectValue placeholder="All creators">
            {(value: string) =>
              value === ALL ? "All creators" : (userNameById.get(value) ?? value)
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All creators</SelectItem>
          {(users.data?.items ?? []).map((user) => (
            <SelectItem key={user.id} value={user.id}>
              {user.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </>
  );
}
