"use client";

import { ClipboardCheck, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Sources } from "@/components/ask/sources";
import { ResultCell } from "@/components/checklist/result-cell";
import { StatusBadge } from "@/components/feedback/status-badge";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormDialog } from "@/components/form/form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { fieldError, isApiError } from "@/lib/api/errors";
import type {
  ChecklistItemKind,
  ChecklistItemResponse,
  ChecklistItemStatus,
} from "@/lib/api/types";
import { canManageProject } from "@/lib/can";
import { groupByFeature } from "@/lib/checklist/operations";
import type { StatusTone } from "@/lib/status";

const COLUMN_COUNT = 6;

/** The server's own message when there is one; it is written for the user. */
function reportFailure(error: unknown): void {
  toast.error(isApiError(error) ? error.message : "That did not save. Try again.");
}

/** Shown wherever a kind is chosen or displayed, so the wording never diverges. */
export const KIND_LABELS: Record<ChecklistItemKind, string> = {
  positive: "Positive",
  negative: "Negative",
};

const RESULT_LABELS: Record<ChecklistItemStatus, string> = {
  untested: "Untested",
  pass: "Pass",
  fail: "Fail",
  blocked: "Blocked",
};

/**
 * `blocked` is a warning, not a danger. "Could not run this" is a different finding
 * from "this behaved wrongly", and colouring them alike is how a blocked test ends up
 * recorded as a failure and the pass rate stops meaning anything.
 */
const RESULT_TONES: Record<ChecklistItemStatus, StatusTone> = {
  untested: "neutral",
  pass: "success",
  fail: "danger",
  blocked: "warning",
};

interface Draft {
  testName: string;
  expectedResult: string;
  kind: ChecklistItemKind;
  notes: string | null;
}

/**
 * The grid, grouped by feature.
 *
 * Both writes open a dialog rather than expanding the row. Editing in place put a
 * textarea, a select and a save button inside a single cell, which made every row
 * tall enough to push the next one off screen -- a tester working down a checklist
 * could see one test at a time. The row now states the outcome; the dialogs do the
 * writing.
 *
 * The split between the two dialogs is the access model, not a layout choice
 * (spec 2.5): **Record result** is open to everyone on every row, while **Edit** is
 * gated on `created_by`/`is_admin`. A tester must be able to record what they saw
 * without being able to rewrite what was expected, because otherwise the cheapest way
 * to make a failing test pass is to edit the expectation.
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
  const [recording, setRecording] = useState<ChecklistItemResponse | null>(null);
  const [editing, setEditing] = useState<ChecklistItemResponse | null>(null);
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
    setEditing(item);
    setDraft({
      testName: item.testName,
      expectedResult: item.expectedResult,
      kind: item.kind,
      notes: item.notes,
    });
  }

  function stopEditing() {
    setEditing(null);
    setDraft(null);
  }

  function saveDefinition(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || !draft) return;
    updateDetail.mutate(
      { itemId: editing.id, ...draft },
      {
        onSuccess: () => {
          toast.success("Test case updated");
          stopEditing();
        },
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
      {/* The page body must never scroll horizontally; six columns of prose will not
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
              ...group.items.map((item) => (
                <TableRow key={item.id} className="align-top">
                  <TableCell className="min-w-56">
                    <div className="flex flex-col gap-1 text-sm">
                      <span className="font-medium">{item.testName}</span>
                      <div className="flex flex-wrap gap-1">
                        {/* Only negatives are badged. Positive is the norm, and
                            badging every row would make the column noise rather than
                            a signal -- the question this answers is "does this
                            feature have failure coverage at all?". */}
                        {item.kind === "negative" ? (
                          <Badge
                            variant="outline"
                            className="text-warning-foreground border-warning/60 w-fit text-xs font-normal"
                          >
                            Negative
                          </Badge>
                        ) : null}
                        {item.source === "manual" ? (
                          <Badge
                            variant="outline"
                            className="w-fit text-xs font-normal"
                          >
                            Hand-written
                          </Badge>
                        ) : null}
                      </div>
                    </div>
                  </TableCell>

                  <TableCell className="min-w-56 text-sm">
                    {item.expectedResult}
                  </TableCell>

                  <TableCell className="min-w-44">
                    <div className="flex flex-col gap-1">
                      <StatusBadge
                        tone={RESULT_TONES[item.status]}
                        label={RESULT_LABELS[item.status]}
                        className="w-fit"
                      />
                      {item.currentResult ? (
                        <span className="text-muted-foreground text-sm">
                          {item.currentResult}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>

                  <TableCell className="text-muted-foreground min-w-40 text-sm">
                    {item.notes ?? "—"}
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
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRecording(item)}
                      >
                        <ClipboardCheck className="size-4" />
                        Record result
                      </Button>
                      {canEdit(item) ? (
                        <>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Edit ${item.testName}`}
                            onClick={() => startEditing(item)}
                          >
                            <Pencil className="size-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Delete ${item.testName}`}
                            onClick={() => setPendingDelete(item)}
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              )),
            ])}
          </TableBody>
        </Table>
      </div>

      {/* A plain Dialog rather than `FormDialog`: `ResultCell` owns its own fields and
          its own submit, and it is deliberately presentational so the same component
          renders in a test without a query client. */}
      <Dialog
        open={recording !== null}
        onOpenChange={(open) => {
          if (!open) setRecording(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record a result</DialogTitle>
            <DialogDescription>{recording?.testName}</DialogDescription>
          </DialogHeader>
          {recording ? (
            <>
              <p className="text-muted-foreground text-sm">
                Expected: {recording.expectedResult}
              </p>
              <ResultCell
                item={recording}
                canEditDefinition={canEdit(recording)}
                isSaving={saveResult.isPending}
                onSave={(input) =>
                  saveResult.mutate(
                    { itemId: recording.id, ...input },
                    {
                      onSuccess: () => {
                        toast.success("Result recorded");
                        setRecording(null);
                      },
                      onError: (error) => reportFailure(error),
                    },
                  )
                }
              />
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <FormDialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) stopEditing();
        }}
        title="Edit the test case"
        description="What it is called, what it should do, and why it exists. The recorded result is not editable here."
        submitLabel="Save changes"
        isPending={updateDetail.isPending}
        error={updateDetail.error}
        onSubmit={saveDefinition}
      >
        {draft ? (
          <>
            <Field>
              <FieldLabel htmlFor="edit-test-name">Test name</FieldLabel>
              <Input
                id="edit-test-name"
                value={draft.testName}
                onChange={(event) =>
                  setDraft({ ...draft, testName: event.target.value })
                }
                aria-invalid={Boolean(fieldError(updateDetail.error, "testName"))}
              />
              {fieldError(updateDetail.error, "testName") ? (
                <FieldError>{fieldError(updateDetail.error, "testName")}</FieldError>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-expected">Expected result</FieldLabel>
              <Textarea
                id="edit-expected"
                className="min-h-24"
                value={draft.expectedResult}
                onChange={(event) =>
                  setDraft({ ...draft, expectedResult: event.target.value })
                }
                aria-invalid={Boolean(fieldError(updateDetail.error, "expectedResult"))}
              />
              {fieldError(updateDetail.error, "expectedResult") ? (
                <FieldError>
                  {fieldError(updateDetail.error, "expectedResult")}
                </FieldError>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-kind">Kind</FieldLabel>
              <Select
                value={draft.kind}
                onValueChange={(value: string | null | undefined) =>
                  setDraft({
                    ...draft,
                    kind: (value as ChecklistItemKind) ?? draft.kind,
                  })
                }
              >
                <SelectTrigger id="edit-kind" className="w-full">
                  <SelectValue>
                    {(value: string) => KIND_LABELS[value as ChecklistItemKind]}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(KIND_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-notes">Notes</FieldLabel>
              <Textarea
                id="edit-notes"
                className="min-h-20"
                value={draft.notes ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, notes: event.target.value || null })
                }
              />
            </Field>
          </>
        ) : null}
      </FormDialog>

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
