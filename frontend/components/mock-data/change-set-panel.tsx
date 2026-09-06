"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormError } from "@/components/form/form-error";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  MockDataChangeOperation,
  MockDataChangeSetApplyResponse,
  MockDataChangeSetResponse,
  MockDataRecordResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

function fieldMapText(fields: Record<string, string>): string {
  const entries = Object.entries(fields);
  if (entries.length === 0) return "(no fields)";
  return entries.map(([key, value]) => `${key}: ${value}`).join(", ");
}

function isOrphaned(
  operation: MockDataChangeOperation,
  records: MockDataRecordResponse[],
): boolean {
  if (operation.op === "add") return false;
  return !records.some((record) => record.id === operation.recordId);
}

function Rationale({ rationale }: { rationale: string }) {
  return (
    <p className="text-muted-foreground text-sm">
      {rationale.trim() ? rationale : "No rationale given."}
    </p>
  );
}

export function MockDataChangeSetPanel({
  changeSet,
  moduleId,
  records,
}: {
  changeSet: MockDataChangeSetResponse;
  moduleId: string;
  records: MockDataRecordResponse[];
}) {
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
        toast.success("Changes applied");
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
      toast.success("Proposals discarded");
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Proposed mock data changes</CardTitle>
        <CardDescription>{changeSet.summary}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {skippedCount !== null ? (
          <Alert>
            <AlertDescription>
              {skippedCount} proposed change{skippedCount === 1 ? "" : "s"} were skipped
              because the record they referred to no longer exists.
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="divide-y">
          {changeSet.operations.map((operation) => {
            const orphaned = isOrphaned(operation, records);
            return (
              <div key={operation.id} className="flex items-start gap-3 py-3">
                <Checkbox
                  checked={Boolean(checked[operation.id])}
                  onCheckedChange={() => toggle(operation.id)}
                  className="mt-1"
                  aria-label="Include this change"
                />
                <div className={orphaned ? "text-muted-foreground flex-1" : "flex-1"}>
                  <p className="font-medium capitalize">{operation.op}</p>
                  {orphaned ? (
                    <p className="text-sm">
                      This record no longer exists — this change will be skipped
                    </p>
                  ) : operation.op === "update" ? (
                    <p className="text-sm">{fieldMapText(operation.changes ?? {})}</p>
                  ) : operation.op === "add" ? (
                    <p className="text-sm">{fieldMapText(operation.fields ?? {})}</p>
                  ) : null}
                  <div className="mt-2">
                    <Rationale rationale={operation.rationale} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <Separator />
        <FormError error={applyMutation.error} />
      </CardContent>
      <CardFooter className="justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => setConfirmingDiscard(true)}
          disabled={applyMutation.isPending || discardMutation.isPending}
        >
          Discard
        </Button>
        <Button
          onClick={handleApply}
          disabled={!hasChecked || applyMutation.isPending || discardMutation.isPending}
        >
          {applyMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
          Apply selected
        </Button>
      </CardFooter>

      <ConfirmDialog
        open={confirmingDiscard}
        onOpenChange={setConfirmingDiscard}
        title="Discard proposed changes"
        description="Discard these proposals? Nothing will be written to the mock dataset."
        confirmLabel="Discard"
        isPending={discardMutation.isPending}
        error={discardMutation.error}
        onConfirm={() => discardMutation.mutate()}
      />
    </Card>
  );
}
