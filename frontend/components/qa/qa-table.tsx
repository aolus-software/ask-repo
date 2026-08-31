"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { QAPairResponse } from "@/lib/api/types";
import { canManageQAPair } from "@/lib/can";
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { keys } from "@/lib/query/keys";
import { qaStatusLabel, qaStatusTone } from "@/lib/status";

const COLUMN_COUNT = 9;

/**
 * One line, full text on hover. `docs/superpowers/specs/2026-08-31-m4-qa-list-design.md`
 * §7.1 keeps prose off the grid on purpose — the detail page is where it is read — so
 * this is a preview, not a substitute.
 */
function TruncatedCell({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span className="block max-w-[24ch] truncate text-left" />}
      >
        {text}
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

function TagsCell({ tags }: { tags: string[] }) {
  if (tags.length === 0) return <span className="text-muted-foreground">—</span>;
  const visible = tags.slice(0, 2);
  const hidden = tags.length - visible.length;
  return (
    <div className="flex max-w-[16ch] items-center gap-1 overflow-hidden">
      {visible.map((tag) => (
        <Badge key={tag} variant="outline" className="shrink-0">
          {tag}
        </Badge>
      ))}
      {hidden > 0 ? (
        <span className="text-muted-foreground shrink-0 text-xs">+{hidden}</span>
      ) : null}
    </div>
  );
}

/**
 * Edit and Delete, gated by `canManageQAPair` — the same ownership rule the backend
 * enforces on `PATCH`/`DELETE /qa-pairs/{id}` (`docs/PRD.md:338`). Editing itself
 * happens on the detail page (`/qa/[id]`, Task 14): the pair is inline-editable there,
 * so "Edit" here is a link, not a form. Delete is the one destructive action this
 * screen performs directly.
 */
function QARowActions({ pair }: { pair: QAPairResponse }) {
  const user = useSession();
  const queryClient = useQueryClient();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.qaPairs.detail(pair.id), { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("QA pair deleted");
      setConfirmingDelete(false);
    },
  });

  if (!canManageQAPair(user, pair)) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${pair.module ?? "this QA pair"}`}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem render={<Link href={`/qa/${pair.id}`} />}>
            <Pencil className="size-4" />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
            <Trash2 className="size-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete this QA pair?"
        description="It is shared with everyone on the instance, and this cannot be undone."
        confirmLabel="Delete"
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

/** Column order is fixed by the design spec: identity, prose, status, tags, project, timestamp, actions. */
export function QATable({
  pairs,
  isLoading,
  projectNames,
}: {
  pairs: QAPairResponse[];
  isLoading: boolean;
  /** Project id → name, for the same page of projects the filter bar's Select uses. A
   * project outside that page (or since deleted) falls back to its id — the pair still
   * names a real project, so showing nothing would be less honest than a raw id. */
  projectNames: Map<string, string>;
}) {
  const router = useRouter();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Module</TableHead>
          <TableHead>Question</TableHead>
          <TableHead>Expected result</TableHead>
          <TableHead>Result</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Tags</TableHead>
          <TableHead>Project</TableHead>
          <TableHead>Last run</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading ? (
          <TableSkeleton columns={COLUMN_COUNT} />
        ) : (
          pairs.map((pair) => (
            <TableRow
              key={pair.id}
              className="cursor-pointer"
              onClick={() => router.push(`/qa/${pair.id}`)}
            >
              <TableCell className="font-medium">{pair.module ?? "—"}</TableCell>
              <TableCell>
                <TruncatedCell text={pair.question} />
              </TableCell>
              <TableCell>
                {pair.referenceAnswer ? (
                  <TruncatedCell text={pair.referenceAnswer} />
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                {pair.answer ? (
                  <TruncatedCell text={pair.answer} />
                ) : (
                  <span className="text-muted-foreground">Not run yet</span>
                )}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <StatusBadge
                    tone={qaStatusTone(pair.status)}
                    label={qaStatusLabel(pair.status)}
                  />
                  {pair.hasPendingRun ? (
                    <Badge variant="outline" className="text-xs">
                      Re-run waiting
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <TagsCell tags={pair.tags} />
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {projectNames.get(pair.projectId) ?? (
                  <span className="font-mono text-xs" title={pair.projectId}>
                    {pair.projectId.slice(0, 8)}
                  </span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground text-sm">
                {pair.lastRunAt ? (
                  <span title={formatAbsolute(pair.lastRunAt)}>
                    {formatRelative(pair.lastRunAt)}
                  </span>
                ) : (
                  "Never"
                )}
              </TableCell>
              <TableCell
                className="text-right"
                onClick={(event) => event.stopPropagation()}
              >
                <QARowActions pair={pair} />
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
