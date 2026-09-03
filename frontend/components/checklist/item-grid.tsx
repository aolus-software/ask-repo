"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Sources } from "@/components/ask/sources";
import { ResultCell } from "@/components/checklist/result-cell";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  useDeleteChecklistItem,
  useSaveChecklistItemResult,
  useUpdateChecklistItemDetail,
} from "@/hooks/use-checklist-mutations";
import { isApiError } from "@/lib/api/errors";
import type { ChecklistItemResponse } from "@/lib/api/types";
import { canManageProject } from "@/lib/can";
import { groupByFeature } from "@/lib/checklist/operations";

const COLUMN_COUNT = 6;

/** The server's own message when there is one; it is written for the user. */
function reportFailure(error: unknown): void {
  toast.error(isApiError(error) ? error.message : "That did not save. Try again.");
}

interface Draft {
  testName: string;
  expectedResult: string;
  notes: string | null;
}

/**
 * The grid, grouped by feature.
 *
 * Two kinds of write live here and they are gated differently, which is the point of
 * the screen (spec 2.5). The definition columns — test name, expected result, notes —
 * are editable only by the person who wrote the row or an admin. The result columns
 * are editable by everyone, because a tester who did not author the checklist must be
 * able to record what they saw without being able to rewrite what was expected.
 *
 * The grouping comes from `groupByFeature`, which is pure and tested on its own; this
 * component computes nothing about ordering.
 */
export function ItemGrid({
  items,
  moduleId,
  user,
}: {
  items: ChecklistItemResponse[];
  moduleId: string;
  user: { id: string; isAdmin: boolean };
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ChecklistItemResponse | null>(
    null,
  );

  const saveResult = useSaveChecklistItemResult(moduleId);
  const updateDetail = useUpdateChecklistItemDetail(moduleId);
  const deleteItem = useDeleteChecklistItem(moduleId);

  // Mirrors the backend gate; it does not replace it. A 403 still surfaces as an error.
  const canEdit = (item: ChecklistItemResponse) => canManageProject(user, item);

  function startEditing(item: ChecklistItemResponse) {
    setEditingId(item.id);
    setDraft({
      testName: item.testName,
      expectedResult: item.expectedResult,
      notes: item.notes,
    });
  }

  function stopEditing() {
    setEditingId(null);
    setDraft(null);
  }

  function saveDefinition(item: ChecklistItemResponse) {
    if (!draft) return;
    updateDetail.mutate(
      { itemId: item.id, ...draft },
      {
        onSuccess: stopEditing,
        onError: (error) => reportFailure(error),
      },
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No test cases yet. Generate the checklist, or add one by hand.
      </p>
    );
  }

  return (
    <>
      {/* The page body must never scroll horizontally; seven columns of prose will not
          fit a phone, so the table scrolls inside its own container. */}
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Test case</TableHead>
              <TableHead>Expected result</TableHead>
              <TableHead>Result</TableHead>
              <TableHead>Notes</TableHead>
              <TableHead>Sources</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groupByFeature(items).map((group) => [
              <TableRow key={`feature-${group.feature}`} className="bg-muted/50">
                <TableCell colSpan={COLUMN_COUNT} className="text-sm font-semibold">
                  {group.feature}
                  <span className="text-muted-foreground ml-2 font-normal">
                    {group.items.length} test{" "}
                    {group.items.length === 1 ? "case" : "cases"}
                  </span>
                </TableCell>
              </TableRow>,
              ...group.items.map((item) => {
                const isEditing = editingId === item.id && draft !== null;
                return (
                  <TableRow key={item.id} className="align-top">
                    <TableCell className="min-w-56">
                      {isEditing && draft ? (
                        <Input
                          aria-label="Test name"
                          value={draft.testName}
                          onChange={(event) =>
                            setDraft({ ...draft, testName: event.target.value })
                          }
                        />
                      ) : (
                        <div className="flex flex-col gap-1 text-sm">
                          <span>{item.testName}</span>
                          {item.source === "manual" ? (
                            <Badge
                              variant="outline"
                              className="w-fit text-xs font-normal"
                            >
                              Hand-written
                            </Badge>
                          ) : null}
                        </div>
                      )}
                    </TableCell>

                    <TableCell className="min-w-56 text-sm">
                      {isEditing && draft ? (
                        <Textarea
                          aria-label="Expected result"
                          value={draft.expectedResult}
                          onChange={(event) =>
                            setDraft({ ...draft, expectedResult: event.target.value })
                          }
                          className="min-h-20"
                        />
                      ) : (
                        item.expectedResult
                      )}
                    </TableCell>

                    <TableCell>
                      <ResultCell
                        item={item}
                        canEditDefinition={canEdit(item)}
                        isSaving={
                          saveResult.isPending &&
                          saveResult.variables?.itemId === item.id
                        }
                        onSave={(input) =>
                          saveResult.mutate(
                            { itemId: item.id, ...input },
                            { onError: (error) => reportFailure(error) },
                          )
                        }
                      />
                    </TableCell>

                    <TableCell className="text-muted-foreground min-w-40 text-sm">
                      {isEditing && draft ? (
                        <Textarea
                          aria-label="Notes"
                          value={draft.notes ?? ""}
                          onChange={(event) =>
                            setDraft({ ...draft, notes: event.target.value || null })
                          }
                          className="min-h-20"
                        />
                      ) : (
                        (item.notes ?? "—")
                      )}
                    </TableCell>

                    <TableCell className="min-w-40">
                      {/* The same component the answer stream renders its sources with.
                          That reuse is why `citations` carries the answer's shape. */}
                      {item.citations && item.citations.length > 0 ? (
                        <Sources citations={item.citations} citedIndexes={[]} />
                      ) : (
                        <span className="text-muted-foreground text-sm">—</span>
                      )}
                    </TableCell>

                    <TableCell className="text-right">
                      {isEditing ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={stopEditing}
                            disabled={updateDetail.isPending}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            onClick={() => saveDefinition(item)}
                            disabled={updateDetail.isPending}
                          >
                            Save
                          </Button>
                        </div>
                      ) : canEdit(item) ? (
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => startEditing(item)}
                          >
                            Edit
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Delete ${item.testName}`}
                            onClick={() => setPendingDelete(item)}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              }),
            ])}
          </TableBody>
        </Table>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Delete this test case?"
        description="The test case and the result recorded against it both go."
        confirmLabel="Delete"
        isPending={deleteItem.isPending}
        error={deleteItem.error}
        onConfirm={() => {
          if (!pendingDelete) return;
          deleteItem.mutate(pendingDelete.id, {
            onSuccess: () => setPendingDelete(null),
            onError: (error) => reportFailure(error),
          });
        }}
      />
    </>
  );
}
