"use client";

import {
  ChevronRight,
  CornerLeftUp,
  File,
  Folder,
  Loader2,
  Search,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useIndexedPaths } from "@/hooks/use-indexed-paths";
import type { IndexedPathEntry } from "@/lib/api/types";
import {
  actionFor,
  breadcrumbTrail,
  normalisePath,
  parentOf,
} from "@/lib/checklist/paths";

/**
 * Browse or search a project's indexed file tree, and pick a path from it.
 *
 * Phase 1.1 (`docs/PRD.md` §2.1). A `source_path` used to be a free-typed field, which
 * assumed the user could produce a correct repository-relative path from memory — fine
 * for the team that stood the instance up, a wall for a QA lead whose first contact
 * with the repository is AskRepo itself.
 *
 * Both halves are here on purpose. Search needs the user to guess at a name; browsing a
 * deep tree to reach `backend/app/api/routes` is a lot of clicks. And the text input
 * stays: someone who can paste the right path should not have to click through to it.
 */
export function PathPicker({
  projectId,
  value,
  onValueChange,
  inputId,
  invalid,
}: {
  projectId: string;
  value: string;
  onValueChange: (path: string) => void;
  inputId: string;
  invalid?: boolean;
}) {
  const t = useTranslations("checklist.pathPicker");
  const [directory, setDirectory] = useState("");
  const [search, setSearch] = useState("");
  const term = search.trim();
  const query = useIndexedPaths(
    projectId,
    term ? { search: term } : { path: directory },
  );
  const trail = breadcrumbTrail(directory);

  function choose(entry: IndexedPathEntry) {
    const action = actionFor(entry, { searching: Boolean(term) });
    setDirectory(action.directory);
    if (action.kind === "select") {
      onValueChange(action.path);
      setSearch("");
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Input
        id={inputId}
        className="font-mono"
        placeholder={t("pathPlaceholder")}
        value={value}
        onChange={(event) => onValueChange(normalisePath(event.target.value))}
        aria-invalid={invalid}
      />

      <div className="border-border overflow-hidden rounded-md border">
        <div className="border-border flex items-center gap-2 border-b px-3 py-2">
          <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <input
            className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t("searchAria")}
          />
          {query.isFetching ? (
            <Loader2
              className="text-muted-foreground size-4 shrink-0 animate-spin"
              aria-hidden
            />
          ) : null}
        </div>

        {term ? null : (
          <div className="border-border flex items-center gap-2 border-b px-3 py-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2"
              disabled={!directory}
              onClick={() => setDirectory(parentOf(directory))}
              aria-label={t("upOneFolder")}
            >
              <CornerLeftUp className="size-4" aria-hidden />
            </Button>
            <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto text-xs">
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground shrink-0"
                onClick={() => setDirectory("")}
              >
                {t("root")}
              </button>
              {trail.map((crumb) => (
                <span key={crumb.path} className="flex shrink-0 items-center gap-1">
                  <ChevronRight className="text-muted-foreground size-4" aria-hidden />
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground font-mono"
                    onClick={() => setDirectory(crumb.path)}
                  >
                    {crumb.label}
                  </button>
                </span>
              ))}
            </nav>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-6 shrink-0 px-2 text-xs"
              disabled={!directory}
              onClick={() => onValueChange(directory)}
            >
              {t("useThisFolder")}
            </Button>
          </div>
        )}

        <ScrollArea className="h-56">
          <PickerRows
            entries={query.data?.entries ?? []}
            selected={value}
            isLoading={query.isLoading}
            isError={query.isError}
            hasProject={Boolean(projectId)}
            onChoose={choose}
          />
        </ScrollArea>

        {query.data?.truncated ? (
          <p className="border-border text-muted-foreground border-t px-3 py-2 text-xs">
            {t("truncated", { count: query.data.entries.length })}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function PickerRows({
  entries,
  selected,
  isLoading,
  isError,
  hasProject,
  onChoose,
}: {
  entries: IndexedPathEntry[];
  selected: string;
  isLoading: boolean;
  isError: boolean;
  hasProject: boolean;
  onChoose: (entry: IndexedPathEntry) => void;
}) {
  const t = useTranslations("checklist.pathPicker");
  if (!hasProject) {
    return <Message>{t("pickProjectFirst")}</Message>;
  }
  if (isError) {
    return <Message>{t("treeUnreadable")}</Message>;
  }
  if (isLoading) {
    return <Message>{t("reading")}</Message>;
  }
  if (entries.length === 0) {
    return <Message>{t("nothingIndexed")}</Message>;
  }
  return (
    <ul className="p-1">
      {entries.map((entry) => (
        <li key={`${entry.kind}:${entry.path}`}>
          <button
            type="button"
            onClick={() => onChoose(entry)}
            aria-current={entry.path === selected ? "true" : undefined}
            className="hover:bg-accent hover:text-accent-foreground aria-current:bg-accent aria-current:text-accent-foreground flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm"
          >
            {entry.kind === "dir" ? (
              <Folder className="text-muted-foreground size-4 shrink-0" aria-hidden />
            ) : (
              <File className="text-muted-foreground size-4 shrink-0" aria-hidden />
            )}
            <span className="truncate font-mono">{entry.name}</span>
            {/* The full path, so a search result says where it lives. */}
            {entry.name === entry.path ? null : (
              <span className="text-muted-foreground truncate font-mono text-xs">
                {entry.path}
              </span>
            )}
            {entry.fileCount === null ? null : (
              <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                {t("fileCount", { count: entry.fileCount })}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Message({ children }: { children: React.ReactNode }) {
  return <p className="text-muted-foreground px-3 py-4 text-sm">{children}</p>;
}
