"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useConversations, useDeleteConversation } from "@/hooks/use-conversations";
import { SORT } from "@/lib/api/endpoints";
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
 */
export function ConversationRail() {
  const router = useRouter();
  const params = useParams<{ conversationId?: string }>();
  const activeId = params?.conversationId;

  const query = useConversations({
    limit: 50,
    sort: SORT.conversations.updatedAt,
    sortDirection: "desc",
  });
  const conversations = query.data?.items ?? [];

  return (
    <aside className="border-border w-full shrink-0 border-b pb-4 md:w-72 md:border-e md:border-b-0 md:pe-4 md:pb-0">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Conversations</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="New conversation"
          render={<Link href="/ask" />}
        >
          <Plus className="size-4" />
        </Button>
      </div>

      <ScrollArea className="h-[calc(100vh-16rem)]">
        {query.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-12 w-full" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <p className="text-muted-foreground p-2 text-xs">
            Nothing yet. Pick a project and ask a question.
          </p>
        ) : (
          <ul className="space-y-1">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group flex items-center gap-1">
                <Link
                  href={`/ask/${conversation.id}`}
                  className={cn(
                    "hover:bg-accent flex-1 rounded-lg p-2 text-sm",
                    conversation.id === activeId && "bg-accent font-medium",
                  )}
                >
                  <span className="block truncate">
                    {conversation.title ?? "Untitled conversation"}
                  </span>
                  <span
                    className="text-muted-foreground block text-xs"
                    title={formatAbsolute(conversation.updatedAt)}
                  >
                    {formatRelative(conversation.updatedAt)}
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
