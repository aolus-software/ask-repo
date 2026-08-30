"use client";

import { Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations, useDeleteConversation } from "@/hooks/use-conversations";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";
import type { ProjectResponse } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { cn } from "@/lib/utils";

function DeleteConversationButton({
  id,
  onDeleted,
}: {
  id: string;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteConversation(id);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Delete conversation"
        className="opacity-0 group-hover:opacity-100"
        onClick={(event) => {
          event.preventDefault();
          setConfirming(true);
        }}
      >
        <Trash2 className="size-4" />
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Delete this conversation?"
        description="Only you can see it, and it cannot be recovered."
        confirmLabel="Delete"
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success("Conversation deleted");
              setConfirming(false);
              onDeleted();
            },
          })
        }
      />
    </>
  );
}

/**
 * The caller's own conversations only. There is no "all conversations" destination
 * anywhere in the product: conversations are private, is_admin does not widen that
 * (docs/PRD.md §4.2), and an affordance implying otherwise is the first step toward
 * someone adding the route.
 *
 * Both filters are applied by the API, not here. Filtering a page client-side would
 * search only the 50 conversations already fetched and quietly miss the rest — the
 * failure mode being an operator concluding a conversation is gone.
 */
export function ConversationRail() {
  const router = useRouter();
  const params = useParams<{ conversationId?: string }>();
  const activeId = params?.conversationId;

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [project, setProject] = useState<ProjectResponse | null>(null);

  // Debounced so typing does not fire a request per keystroke — the same 300ms the
  // list screens use (`components/layout/list-toolbar.tsx`).
  useEffect(() => {
    if (searchInput === search) return;
    const timer = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput, search]);

  // Also the source of the names shown on each row: the filter needs the project
  // list anyway, so resolving ids from it costs nothing extra. Same page size and
  // ordering as ProjectPicker, so both read one cached query rather than two.
  const projectsQuery = useProjects({
    limit: 100,
    sort: SORT.projects.updatedAt,
    sortDirection: "desc",
  });
  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const projectNames = useMemo(
    () => new Map(projects.map((item) => [item.id, item.name])),
    [projects],
  );

  const query = useConversations({
    limit: 50,
    sort: SORT.conversations.updatedAt,
    sortDirection: "desc",
    search: search || undefined,
    projectId: project?.id,
  });
  const conversations = query.data?.items ?? [];
  const isFiltered = Boolean(search) || project !== null;

  return (
    // Pinned beside the answer on desktop, so switching conversations never means
    // scrolling back up to find the list. `top-16` and the height both derive from the
    // navbar's 4rem (`docs/design.md` → Layout); `self-start` is what makes it stick at
    // all, because a stretched flex item is already the full height of the row and has
    // nowhere left to travel.
    <aside className="border-border w-full shrink-0 border-b pb-4 md:sticky md:top-16 md:flex md:h-[calc(100vh-4rem)] md:w-72 md:flex-col md:self-start md:border-e md:border-b-0 md:pe-4 md:pb-0">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Conversations</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="New conversation"
          nativeButton={false}
          render={<Link href="/ask" />}
        >
          <Plus className="size-4" />
        </Button>
      </div>

      <div className="mb-4 space-y-2">
        <div className="relative">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            className="pl-9"
            placeholder="Search conversations"
            aria-label="Search conversations"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>

        {/* A combobox rather than a select for the same reason ProjectPicker uses one:
            the project list is instance-wide and unbounded, so typing to narrow is the
            only thing that scales. Unlike the picker, every project is selectable —
            this filters conversations that already exist, and one against a project
            that has since stopped being `ready` still needs to be findable.
            Clearing the input is what resets the filter to every project. */}
        <Combobox
          items={projects}
          value={project}
          onValueChange={setProject}
          itemToStringLabel={(item: ProjectResponse) => item.name}
        >
          <ComboboxInput
            className="w-full"
            showClear
            placeholder={projectsQuery.isLoading ? "Loading projects…" : "All projects"}
            aria-label="Filter by project"
          />
          <ComboboxContent>
            <ComboboxEmpty>
              {projectsQuery.isLoading ? "Loading…" : "No project matches."}
            </ComboboxEmpty>
            <ComboboxList>
              {(item: ProjectResponse) => (
                <ComboboxItem key={item.id} value={item}>
                  <span className="truncate">{item.name}</span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </div>

      {/* Fixed height on mobile, where the rail is a stacked block. On desktop it
          takes whatever the pinned column has left — `min-h-0` because a flex child
          refuses to shrink below its content without it, which would push the list
          past the bottom of the viewport instead of scrolling it. */}
      <ScrollArea className="h-[calc(100vh-16rem)] md:h-auto md:min-h-0 md:flex-1">
        {query.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <p className="text-muted-foreground p-2 text-xs">
            {isFiltered
              ? "No conversation matches."
              : "Nothing yet. Pick a project and ask a question."}
          </p>
        ) : (
          <ul className="space-y-1">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group flex items-center gap-1">
                <Link
                  href={`/ask/${conversation.id}`}
                  className={cn(
                    "hover:bg-accent min-w-0 flex-1 rounded-lg p-2 text-sm",
                    conversation.id === activeId && "bg-accent font-medium",
                  )}
                >
                  <span className="block truncate">
                    {conversation.title ?? "Untitled conversation"}
                  </span>
                  <span className="text-muted-foreground flex items-center gap-1 text-xs">
                    {/* Absent when the project is outside the page of 100 fetched
                        above, or has been deleted. Showing nothing is the honest
                        result; a placeholder would read as a project called that. */}
                    {projectNames.has(conversation.projectId) ? (
                      <>
                        <span className="truncate">
                          {projectNames.get(conversation.projectId)}
                        </span>
                        <span aria-hidden>·</span>
                      </>
                    ) : null}
                    <span
                      className="shrink-0"
                      title={formatAbsolute(conversation.updatedAt)}
                    >
                      {formatRelative(conversation.updatedAt)}
                    </span>
                  </span>
                </Link>
                <DeleteConversationButton
                  id={conversation.id}
                  onDeleted={() => {
                    if (conversation.id === activeId) router.replace("/ask");
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </aside>
  );
}
