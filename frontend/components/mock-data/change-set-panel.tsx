"use client";

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
  MockDataChangeOperation,
  MockDataChangeSetApplyResponse,
  MockDataChangeSetResponse,
  MockDataRecordResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

function fieldMapText(fields: Record<string, string>, noFields: string): string {
  const entries = Object.entries(fields);
  if (entries.length === 0) return noFields;
  return entries.map(([key, value]) => `${key}: ${value}`).join(", ");
}

/** The first few fields of a record, enough to recognise it by. */
function identifyingFields(record: MockDataRecordResponse): string {
  return Object.entries(record.fields)
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${value}`)
    .join(", ");
}

function isOrphaned(
  operation: MockDataChangeOperation,
  records: MockDataRecordResponse[],
): boolean {
  if (operation.op === "add") return false;
  return !records.some((record) => record.id === operation.recordId);
}

export function MockDataChangeSetPanel({
  changeSet,
  moduleId,
  records,
  canApply,
}: {
  changeSet: MockDataChangeSetResponse;
  moduleId: string;
  records: MockDataRecordResponse[];
  /** Mirrors the backend's `mockdata.edit` gate; it does not replace it. */
  canApply: boolean;
}) {
  const t = useTranslations("mockData.changeSetPanel");
  const queryClient = useQueryClient();
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const operation of changeSet.operations) {
      initial[operation.id] = !isOrphaned(operation, records);
    }
    return initial;
  });
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);
  const [skippedCount, setSkippedCount] = useState<number | null>(null);

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: keys.mockData.detail(moduleId) });
    queryClient.invalidateQueries({
      queryKey: keys.mockDataChangeSets.forModule(moduleId),
    });
  }

  const applyMutation = useMutation({
    mutationFn: (body: { operationIds?: string[] }) =>
      apiFetch<MockDataChangeSetApplyResponse>(
        endpoints.mockDataChangeSets.apply(changeSet.id),
        { method: "POST", body: JSON.stringify(body) },
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
      apiFetch<MockDataChangeSetResponse>(
        endpoints.mockDataChangeSets.discard(changeSet.id),
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

  const hasChecked = Object.values(checked).some(Boolean);
  const counts = countOperations(changeSet.operations);

  function renderRow(operation: MockDataChangeOperation) {
    const orphaned = isOrphaned(operation, records);
    // Which record an update or remove lands on -- the decision this panel exists
    // for. The id is always shown; a record still in the dataset adds its first
    // fields so a reviewer can recognise it without cross-checking the table.
    const target =
      operation.op === "add"
        ? undefined
        : records.find((record) => record.id === operation.recordId);
    const recordLabel = t.rich("recordLine", {
      recordId: operation.recordId ?? "",
      id: (chunks) => <span className="font-mono">{chunks}</span>,
    });
    return (
      <OperationRow
        key={operation.id}
        checked={Boolean(checked[operation.id])}
        onToggle={() => toggle(operation.id)}
        orphaned={orphaned}
      >
        <p className="font-medium">{t(`ops.${operation.op}`)}</p>
        {operation.op !== "add" && operation.recordId ? (
          <p className="text-muted-foreground text-xs">
            {recordLabel}
            {target ? ` · ${identifyingFields(target)}` : null}
          </p>
        ) : null}
        {orphaned ? (
          <p className="text-sm">{t("orphaned")}</p>
        ) : operation.op === "update" ? (
          <p className="text-sm">
            {fieldMapText(operation.changes ?? {}, t("noFields"))}
          </p>
        ) : operation.op === "add" ? (
          <p className="text-sm">
            {fieldMapText(operation.fields ?? {}, t("noFields"))}
          </p>
        ) : null}
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
          targetType="mock_data_change_set"
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
