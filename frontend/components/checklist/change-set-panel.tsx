"use client";

import { useKindLabel } from "@/components/checklist/use-kind-label";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  OperationCountsLine,
  OperationGroups,
  countOperations,
} from "@/components/change-sets/operation-groups";
import {
  OperationRationale,
  OperationRow,
} from "@/components/change-sets/operation-row";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormError } from "@/components/form/form-error";
import { FeedbackControl } from "@/components/output-feedback/feedback-control";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  ChangeOperation,
  ChangeSetApplyResponse,
  ChecklistChangeSetResponse,
  ChecklistItemResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** The camelCase field names with a label (`checklist.changeSetPanel.fields.*`); unknown keys fall back to the key itself. */
const LABELLED_FIELDS = [
  "feature",
  "testName",
  "expectedResult",
  "currentResult",
  "status",
  "kind",
  "notes",
] as const;

function isLabelledField(field: string): field is (typeof LABELLED_FIELDS)[number] {
  return (LABELLED_FIELDS as readonly string[]).includes(field);
}

/** The value of `field` on the item currently in the grid, rendered as text for the diff. */
function oldFieldValue(item: ChecklistItemResponse, field: string): string {
  const value = (item as unknown as Record<string, unknown>)[field];
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** An `update`/`remove` op is only ever skipped for one reason: its target left the grid. */
function targetItem(
  operation: ChangeOperation,
  items: ChecklistItemResponse[],
): ChecklistItemResponse | undefined {
  return items.find((item) => item.id === operation.itemId);
}

function isOrphaned(
  operation: ChangeOperation,
  items: ChecklistItemResponse[],
): boolean {
  if (operation.op === "add") return false;
  return targetItem(operation, items) === undefined;
}

export function ChangeSetPanel({
  changeSet,
  moduleId,
  items,
  canApply,
}: {
  changeSet: ChecklistChangeSetResponse;
  moduleId: string;
  items: ChecklistItemResponse[];
  /** Mirrors the backend's `changeset.apply` gate; it does not replace it. */
  canApply: boolean;
}) {
  const t = useTranslations("checklist.changeSetPanel");
  const negativeLabel = useKindLabel()("negative");
  const queryClient = useQueryClient();
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const operation of changeSet.operations) {
      initial[operation.id] = !isOrphaned(operation, items);
    }
    return initial;
  });
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const [skippedCount, setSkippedCount] = useState<number | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: keys.checklistModules.detail(moduleId) });
    queryClient.invalidateQueries({
      queryKey: keys.checklistChangeSets.forModule(moduleId),
    });
    queryClient.invalidateQueries({ queryKey: keys.checklistItems.all });
  }

  const applyMutation = useMutation({
    mutationFn: (body: { operationIds?: string[] }) =>
      apiFetch<ChangeSetApplyResponse>(
        endpoints.checklistChangeSets.apply(changeSet.id),
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      ),
    onSuccess: (data) => {
      invalidate();
      if (data.skippedOperationIds.length > 0) {
        setSkippedCount(data.skippedOperationIds.length);
      } else {
        toast.success(t("applied"));
      }
    },
  });

  const discardMutation = useMutation({
    mutationFn: () =>
      apiFetch<ChecklistChangeSetResponse>(
        endpoints.checklistChangeSets.discard(changeSet.id),
        {
          method: "POST",
        },
      ),
    onSuccess: () => {
      invalidate();
      toast.success(t("discarded"));
      setConfirmingDiscard(false);
    },
  });

  function toggle(operationId: string) {
    setChecked((prev) => ({ ...prev, [operationId]: !prev[operationId] }));
  }

  function handleApply() {
    const allChecked = changeSet.operations.every((operation) => checked[operation.id]);
    applyMutation.mutate(
      allChecked
        ? {}
        : {
            operationIds: changeSet.operations
              .filter((operation) => checked[operation.id])
              .map((operation) => operation.id),
          },
    );
  }

  const counts = countOperations(changeSet.operations);
  const hasChecked = Object.values(checked).some(Boolean);

  function renderRow(operation: ChangeOperation) {
    const orphaned = isOrphaned(operation, items);
    const item = targetItem(operation, items);

    return (
      <OperationRow
        key={operation.id}
        checked={Boolean(checked[operation.id])}
        onToggle={() => toggle(operation.id)}
        orphaned={orphaned}
      >
        {operation.op === "add" ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{operation.testName}</p>
              {/* Badged before the reviewer decides, not after: knowing which
                  proposals are failure cases is most of what tells them
                  whether the set is worth accepting. */}
              {operation.kind === "negative" ? (
                <Badge
                  variant="outline"
                  className="text-warning-text border-warning/60 text-xs font-normal"
                >
                  {negativeLabel}
                </Badge>
              ) : null}
            </div>
            <p className="text-muted-foreground text-sm">{operation.feature}</p>
            {operation.expectedResult ? (
              <p className="mt-1 text-sm">{operation.expectedResult}</p>
            ) : null}
          </>
        ) : orphaned || !item ? (
          <p className="text-sm">{t("orphaned")}</p>
        ) : operation.op === "update" ? (
          <>
            <p className="font-medium">{item.testName}</p>
            <div className="mt-1 space-y-1">
              {Object.entries(operation.changes ?? {}).map(([field, next]) => (
                <p key={field} className="text-sm">
                  <span className="text-muted-foreground">
                    {isLabelledField(field) ? t(`fields.${field}`) : field}:{" "}
                  </span>
                  {oldFieldValue(item, field)}
                  <span className="text-muted-foreground"> → </span>
                  {next}
                </p>
              ))}
            </div>
          </>
        ) : (
          <>
            <p className="font-medium">{item.testName}</p>
            <p className="text-muted-foreground text-sm">{item.feature}</p>
          </>
        )}
        <div className="mt-2">
          <OperationRationale rationale={operation.rationale} />
        </div>
      </OperationRow>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{changeSet.summary}</CardDescription>
        <OperationCountsLine counts={counts} />
      </CardHeader>
      <CardContent className="space-y-4">
        {skippedCount !== null ? (
          <Alert>
            <AlertDescription>{t("skipped", { count: skippedCount })}</AlertDescription>
          </Alert>
        ) : null}

        <OperationGroups operations={changeSet.operations} renderRow={renderRow} />

        <FormError error={applyMutation.error} />
      </CardContent>
      <CardFooter className="justify-between gap-2">
        <FeedbackControl
          targetType="checklist_change_set"
          targetId={changeSet.id}
          initial={changeSet.myFeedback}
          className="mt-0"
        />
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setConfirmingDiscard(true)}
            disabled={!canApply || applyMutation.isPending || discardMutation.isPending}
          >
            {t("discard")}
          </Button>
          <Button
            onClick={handleApply}
            disabled={
              !canApply ||
              !hasChecked ||
              applyMutation.isPending ||
              discardMutation.isPending
            }
          >
            {applyMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : null}
            {t("applySelected")}
          </Button>
        </div>
      </CardFooter>

      <ConfirmDialog
        open={confirmingDiscard}
        onOpenChange={setConfirmingDiscard}
        title={t("discardTitle")}
        description={t("discardDescription")}
        confirmLabel={t("discard")}
        isPending={discardMutation.isPending}
        error={discardMutation.error}
        onConfirm={() => discardMutation.mutate()}
      />
    </Card>
  );
}
