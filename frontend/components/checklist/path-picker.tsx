"use client";

import {
  ChevronRight,
  CornerLeftUp,
  File,
  Folder,
  Loader2,
  Search,
} from "lucide-react";
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

const ROOT_LABEL = "Repository";

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
        placeholder="backend/app/auth"
        value={value}
        onChange={(event) => onValueChange(normalisePath(event.target.value))}
        aria-invalid={invalid}
      />

      <div className="border-border overflow-hidden rounded-md border">
        <div className="border-border flex items-center gap-2 border-b px-3 py-2">
          <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <input
            className="placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
            placeholder="Search files and folders"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search the repository tree"
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
              aria-label="Go up one folder"
            >
              <CornerLeftUp className="size-4" aria-hidden />
            </Button>
            <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto text-xs">
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground shrink-0"
                onClick={() => setDirectory("")}
              >
                {ROOT_LABEL}
              </button>
              {trail.map((crumb) => (
                <span key={crumb.path} className="flex shrink-0 items-center gap-1">
                  <ChevronRight className="text-muted-foreground size-3" aria-hidden />
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
              Use this folder
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
            Showing the first {query.data.entries.length} matches. Narrow the search to
            see the rest.
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
  if (!hasProject) {
    return <Message>Pick a project first.</Message>;
  }
  if (isError) {
    return (
      <Message>The repository tree could not be read. Try again in a moment.</Message>
    );
  }
  if (isLoading) {
    return <Message>Reading the indexed tree…</Message>;
  }
  if (entries.length === 0) {
    return <Message>Nothing indexed here.</Message>;
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
                {entry.fileCount} {entry.fileCount === 1 ? "file" : "files"}
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
