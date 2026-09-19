"use client";

import { MessagesSquare, PanelLeft, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
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
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
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
 * The list itself — search, project filter, and the conversations — with no opinion
 * about what contains it. Rendered twice: inline in the desktop sidebar, and inside a
 * `Sheet` on mobile (`onNavigate` closes that sheet when a row is followed).
 *
 * The caller's own conversations only. There is no "all conversations" destination
 * anywhere in the product: conversations are private, is_admin does not widen that
 * (docs/PRD.md §4.2), and an affordance implying otherwise is the first step toward
 * someone adding the route.
 *
 * Both filters are applied by the API, not here. Filtering a page client-side would
 * search only the 50 conversations already fetched and quietly miss the rest — the
 * failure mode being an operator concluding a conversation is gone.
 */
function ConversationList({
  activeId,
  onNavigate,
  collapseAction,
}: {
  activeId: string | undefined;
  onNavigate?: () => void;
  /** The desktop collapse toggle, rendered beside the title. Absent on mobile,
   * where the sheet's own close affordance already covers this. */
  collapseAction?: React.ReactNode;
}) {
  const router = useRouter();

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
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-4 flex items-center justify-between gap-1">
        <h2 className="text-sm font-medium">Conversations</h2>
        <div className="flex items-center">
          <Button
            variant="ghost"
            size="icon"
            aria-label="New conversation"
            nativeButton={false}
            render={<Link href="/ask" onClick={onNavigate} />}
          >
            <Plus className="size-4" />
          </Button>
          {collapseAction}
        </div>
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
              {projectsQuery.isLoading
                ? "Loading…"
                : projectsQuery.isError
                  ? "Could not load projects."
                  : "No project matches."}
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

      {/* `min-h-0` because a flex child refuses to shrink below its content without
          it, which would push the list past the bottom of whatever contains this —
          the pinned desktop column, or the sheet's own scroll area on mobile. No
          fixed height of its own: that is the containing element's job, and a fixed
          height here is what used to reserve a screenful of blank space on mobile
          even for a two-row list. */}
      <ScrollArea className="min-h-0 flex-1">
        {query.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : query.isError ? (
          /* Ahead of the empty state, never behind it: `data` is undefined on a
             failure, so without this branch a dropped request tells someone with a
             full history that they have none -- which reads as data loss rather than
             a retryable error (`docs/ui-audit-findings.md` §U7.5). */
          <ListError error={query.error} onRetry={() => query.refetch()} />
        ) : conversations.length === 0 ? (
          <EmptyState
            size="compact"
            description={
              isFiltered
                ? "No conversation matches."
                : "Nothing yet. Pick a project and ask a question."
            }
          />
        ) : (
          <ul className="space-y-1">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group flex items-center gap-1">
                <Link
                  href={`/ask/${conversation.id}`}
                  onClick={onNavigate}
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
                    onNavigate?.();
                    if (conversation.id === activeId) router.replace("/ask");
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}

const COLLAPSE_STORAGE_KEY = "askrepo.conversation-rail-collapsed";

// A plain useState seeded from localStorage would read `false` on the server (no
// `window`) and the real stored value on the client's first render — a hydration
// mismatch, since this boolean picks between two different DOM subtrees (a full
// `<aside>` versus a slim strip) that both mount immediately, unlike
// `refinement-drawer.tsx`'s remembered width, which lives inside a Sheet that is not
// in the DOM at all until opened. `useSyncExternalStore` is the sanctioned fix for
// exactly this shape of problem — see `hooks/use-mobile.ts`'s `useIsMobile`, which
// hits the same issue for `window.innerWidth`. `getServerSnapshot` matches the
// pre-hydration render exactly, and the client corrects itself immediately after,
// with no `setState` in an effect (`react-hooks/set-state-in-effect`,
// `.claude/rules/forms.md` §6).
const collapseListeners = new Set<() => void>();

function subscribeToCollapsed(callback: () => void): () => void {
  collapseListeners.add(callback);
  // Cross-tab: another tab toggling the same preference updates this one too.
  window.addEventListener("storage", callback);
  return () => {
    collapseListeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

/**
 * `localStorage` throws rather than returning null in a few configurations
 * (Safari's private mode historically, an iframe with third-party storage
 * blocked). Losing the remembered collapse state is a lesser problem than the
 * rail failing to render at all, so both accessors swallow the failure — the
 * same trade-off `refinement-drawer.tsx` makes for its remembered width.
 */
function getCollapsedSnapshot(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function getServerCollapsedSnapshot(): boolean {
  return false;
}

function setCollapsedPreference(collapsed: boolean): void {
  try {
    window.localStorage.setItem(COLLAPSE_STORAGE_KEY, String(collapsed));
  } catch {
    // The choice simply will not persist; the toggle still works this session.
  }
  // `storage` fires only in OTHER tabs, never this one — this tab's own listeners
  // (this hook's own re-render) have to be told directly.
  for (const listener of collapseListeners) listener();
}

function useCollapsedPreference(): boolean {
  return useSyncExternalStore(
    subscribeToCollapsed,
    getCollapsedSnapshot,
    getServerCollapsedSnapshot,
  );
}

/**
 * Desktop gets the list pinned beside the answer by default, so switching
 * conversations never means scrolling back up to find it — but it collapses to a
 * slim strip on request, for the same reason the answer column itself wants the
 * room: a long answer or a wide code block benefits from the full page width, and
 * not everyone wants the list visible on every turn. The choice is remembered in
 * `localStorage`, the same phase-1 no-preference-store trade-off
 * `refinement-drawer.tsx` already makes for its own remembered width.
 * `top-16` and the height both derive from the navbar's 4rem
 * (`docs/design.md` → Layout); `self-start` is what makes it stick at all, because a
 * stretched flex item is already the full height of the row and has nowhere left to
 * travel.
 *
 * Mobile gets a collapsed-by-default toggle instead of the same block stacked inline
 * above the page content. Stacking it unconditionally used to do two things wrong at
 * once: the list's own scroll area was pinned to a fixed height regardless of how
 * many conversations existed, so a two-conversation account showed most of a screen
 * of empty space — and the actual Ask panel this page exists for sat below that
 * empty space, off screen, with no control to get past it faster than scrolling.
 */
export function ConversationRail() {
  const params = useParams<{ conversationId?: string }>();
  const activeId = params?.conversationId;
  const [mobileOpen, setMobileOpen] = useState(false);
  const collapsed = useCollapsedPreference();

  function toggleCollapsed() {
    setCollapsedPreference(!collapsed);
  }

  return (
    <>
      {collapsed ? (
        <div className="border-border sticky top-16 hidden h-[calc(100vh-4rem)] w-10 shrink-0 flex-col items-center self-start border-e pt-1 md:flex">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Show conversations"
            onClick={toggleCollapsed}
          >
            <PanelLeft className="size-4" />
          </Button>
        </div>
      ) : (
        <aside className="border-border sticky top-16 hidden h-[calc(100vh-4rem)] w-72 shrink-0 flex-col self-start border-e pe-4 md:flex">
          <ConversationList
            activeId={activeId}
            collapseAction={
              <Button
                variant="ghost"
                size="icon"
                aria-label="Hide conversations"
                onClick={toggleCollapsed}
              >
                <PanelLeft className="size-4" />
              </Button>
            }
          />
        </aside>
      )}

      <div className="md:hidden">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger
            render={<Button variant="outline" className="w-full justify-start" />}
          >
            <MessagesSquare className="size-4" />
            Conversations
          </SheetTrigger>
          <SheetContent side="left" className="flex w-full flex-col gap-0 sm:max-w-sm">
            <SheetHeader className="border-border border-b">
              <SheetTitle>Conversations</SheetTitle>
            </SheetHeader>
            <div className="min-h-0 flex-1 p-4">
              <ConversationList
                activeId={activeId}
                onNavigate={() => setMobileOpen(false)}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
