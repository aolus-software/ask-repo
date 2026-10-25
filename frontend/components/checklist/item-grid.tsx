"use client";

import { ClipboardCheck, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { Sources } from "@/components/ask/sources";
import { ResultCell } from "@/components/checklist/result-cell";
import { StatusBadge } from "@/components/feedback/status-badge";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormDialog } from "@/components/form/form-dialog";
import { EmptyState } from "@/components/feedback/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { useProject } from "@/hooks/use-projects";
import { useErrorText, useFieldErrorText } from "@/lib/i18n/error-text";
import type { ChecklistItemKind, ChecklistItemResponse } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";
import { groupByFeature } from "@/lib/checklist/operations";
import {
  checklistItemResultLabelKey,
  checklistItemResultTone,
  testCaseKindTone,
} from "@/lib/status";

const COLUMN_COUNT = 6;

const KINDS: ChecklistItemKind[] = ["positive", "negative"];

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
  isGenerating,
}: {
  items: ChecklistItemResponse[];
  moduleId: string;
  /** While a generation runs the empty state must not invite starting another. */
  isGenerating: boolean;
}) {
  const t = useTranslations("checklist");
  const tStatus = useTranslations("status");
  const errorText = useErrorText();
  const fieldErrorText = useFieldErrorText();
  function reportFailure(error: unknown): void {
    toast.error(errorText(error));
  }
  const [recording, setRecording] = useState<ChecklistItemResponse | null>(null);
  const [editing, setEditing] = useState<ChecklistItemResponse | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ChecklistItemResponse | null>(
    null,
  );

  const saveResult = useSaveChecklistItemResult(moduleId);
  const updateDetail = useUpdateChecklistItemDetail(moduleId);
  const testNameError = fieldErrorText(updateDetail.error, "testName");
  const expectedResultError = fieldErrorText(updateDetail.error, "expectedResult");
  const deleteItem = useDeleteChecklistItem(moduleId);
  const project = useProject(items[0]?.projectId ?? "");

  // Mirrors the backend gate; it does not replace it. A 403 still surfaces as an error.
  const canEdit = () =>
    project.data ? can(project.data, PERMISSION.ITEM_EDIT) : false;
  // Every system role carries `result.record` (docs/PRD.md §4.3), so this is always
  // true in practice -- checked explicitly anyway, so its absence elsewhere is never
  // mistaken for an oversight.
  const canRecord = () =>
    project.data ? can(project.data, PERMISSION.RESULT_RECORD) : false;

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
          toast.success(t("itemGrid.updated"));
          stopEditing();
        },
        onError: (error) => reportFailure(error),
      },
    );
  }

  if (items.length === 0) {
    return (
      <Card className="p-0">
        <EmptyState
          icon={ClipboardCheck}
          title={
            isGenerating ? t("itemGrid.generatingTitle") : t("itemGrid.emptyTitle")
          }
          description={
            isGenerating
              ? t("itemGrid.generatingDescription")
              : t("itemGrid.emptyDescription")
          }
        />
      </Card>
    );
  }

  return (
    <>
      {/* Every table sits inside a Card — `.claude/rules/design-system.md` §11 — so
          this one no longer shows the page background through it the way it did
          before. The scroll container is nested *inside* the Card rather than on it:
          Card's own `overflow-hidden` would otherwise fight a `overflow-x-auto` on
          the same element. The page body must never scroll horizontally; six columns
          of prose will not fit a phone, so the table scrolls inside its own
          container. */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("itemGrid.columns.testCase")}</TableHead>
                <TableHead>{t("itemGrid.columns.expectedResult")}</TableHead>
                <TableHead>{t("itemGrid.columns.result")}</TableHead>
                <TableHead>{t("itemGrid.columns.notes")}</TableHead>
                <TableHead>{t("itemGrid.columns.sources")}</TableHead>
                <TableHead className="text-right">
                  {t("itemGrid.columns.actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groupByFeature(items).map((group) => [
                <TableRow key={`feature-${group.feature}`} className="bg-muted/50">
                  <TableCell colSpan={COLUMN_COUNT} className="text-sm font-semibold">
                    {group.feature}
                    <span className="text-muted-foreground ml-2 font-normal">
                      {t("itemGrid.testCaseCount", { count: group.items.length })}
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
                            <StatusBadge
                              tone={testCaseKindTone(item.kind)}
                              label={t("kinds.negative")}
                              className="w-fit text-xs font-normal"
                            />
                          ) : null}
                          {item.source === "manual" ? (
                            <Badge
                              variant="outline"
                              className="w-fit text-xs font-normal"
                            >
                              {t("itemGrid.handWritten")}
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
                          tone={checklistItemResultTone(item.status)}
                          label={tStatus(checklistItemResultLabelKey(item.status))}
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
                        {canRecord() ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setRecording(item)}
                          >
                            <ClipboardCheck className="size-4" />
                            {t("itemGrid.recordResult")}
                          </Button>
                        ) : null}
                        {canEdit() ? (
                          <>
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label={t("itemGrid.editAria", {
                                name: item.testName,
                              })}
                              onClick={() => startEditing(item)}
                            >
                              <Pencil className="size-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label={t("itemGrid.deleteAria", {
                                name: item.testName,
                              })}
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
      </Card>

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
            <DialogTitle>{t("itemGrid.recordTitle")}</DialogTitle>
            <DialogDescription>{recording?.testName}</DialogDescription>
          </DialogHeader>
          {recording ? (
            <>
              <p className="text-muted-foreground text-sm">
                {t("itemGrid.expectedLine", { expected: recording.expectedResult })}
              </p>
              <ResultCell
                item={recording}
                canEditDefinition={canEdit()}
                isSaving={saveResult.isPending}
                onSave={(input) =>
                  saveResult.mutate(
                    { itemId: recording.id, ...input },
                    {
                      onSuccess: () => {
                        toast.success(t("itemGrid.resultRecorded"));
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
        title={t("itemGrid.editTitle")}
        description={t("itemGrid.editDescription")}
        submitLabel={t("itemGrid.saveChanges")}
        isPending={updateDetail.isPending}
        error={updateDetail.error}
        onSubmit={saveDefinition}
      >
        {draft ? (
          <>
            <Field>
              <FieldLabel htmlFor="edit-test-name">{t("itemGrid.testName")}</FieldLabel>
              <Input
                id="edit-test-name"
                value={draft.testName}
                onChange={(event) =>
                  setDraft({ ...draft, testName: event.target.value })
                }
                aria-invalid={Boolean(testNameError)}
              />
              {testNameError ? <FieldError>{testNameError}</FieldError> : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-expected">
                {t("itemGrid.expectedResult")}
              </FieldLabel>
              <Textarea
                id="edit-expected"
                className="min-h-24"
                value={draft.expectedResult}
                onChange={(event) =>
                  setDraft({ ...draft, expectedResult: event.target.value })
                }
                aria-invalid={Boolean(expectedResultError)}
              />
              {expectedResultError ? (
                <FieldError>{expectedResultError}</FieldError>
              ) : null}
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-kind">{t("itemGrid.kind")}</FieldLabel>
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
                    {(value: string) => t(`kinds.${value as ChecklistItemKind}`)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`kinds.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-notes">{t("itemGrid.notes")}</FieldLabel>
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
        title={t("itemGrid.deleteTitle")}
        description={t("itemGrid.deleteDescription")}
        confirmLabel={t("itemGrid.delete")}
        isPending={deleteItem.isPending}
        error={deleteItem.error}
        onConfirm={() => {
          if (!pendingDelete) return;
          deleteItem.mutate(pendingDelete.id, {
            onSuccess: () => {
              toast.success(t("itemGrid.deleted"));
              setPendingDelete(null);
            },
            onError: (error) => reportFailure(error),
          });
        }}
      />
    </>
  );
}
