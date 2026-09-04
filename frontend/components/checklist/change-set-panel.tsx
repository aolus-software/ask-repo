"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormError } from "@/components/form/form-error";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  ChangeOperation,
  ChangeSetApplyResponse,
  ChecklistChangeSetResponse,
  ChecklistItemResponse,
} from "@/lib/api/types";
import { summariseOperations } from "@/lib/checklist/operations";
import { keys } from "@/lib/query/keys";

/** camelCase field name -> the label shown on a Changed row. Unknown keys fall back to the key itself. */
const FIELD_LABELS: Record<string, string> = {
  feature: "Feature",
  testName: "Test name",
  expectedResult: "Expected result",
  currentResult: "Current result",
  status: "Status",
  kind: "Kind",
  notes: "Notes",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
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

function OperationRow({
  checked,
  onToggle,
  orphaned,
  children,
}: {
  checked: boolean;
  onToggle: () => void;
  orphaned: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-3">
      <Checkbox
        checked={checked}
        onCheckedChange={onToggle}
        className="mt-1"
        aria-label="Include this change"
      />
      <div className={orphaned ? "text-muted-foreground flex-1" : "flex-1"}>
        {children}
      </div>
    </div>
  );
}

function Rationale({ rationale }: { rationale: string }) {
  return (
    <p className="text-muted-foreground text-sm">
      {rationale.trim() ? rationale : "No rationale given."}
    </p>
  );
}

export function ChangeSetPanel({
  changeSet,
  moduleId,
  items,
}: {
  changeSet: ChecklistChangeSetResponse;
  moduleId: string;
  items: ChecklistItemResponse[];
}) {
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
        toast.success("Changes applied");
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

  const counts = summariseOperations(changeSet.operations);
  const added = changeSet.operations.filter((operation) => operation.op === "add");
  const updated = changeSet.operations.filter((operation) => operation.op === "update");
  const removed = changeSet.operations.filter((operation) => operation.op === "remove");
  const hasChecked = Object.values(checked).some(Boolean);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Proposed changes</CardTitle>
        <CardDescription>{changeSet.summary}</CardDescription>
        <p className="text-muted-foreground text-sm">
          {counts.added} added, {counts.updated} changed, {counts.removed} removed
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {skippedCount !== null ? (
          <Alert>
            <AlertDescription>
              {skippedCount} proposed change{skippedCount === 1 ? "" : "s"} were skipped
              because the test case they referred to no longer exists.
            </AlertDescription>
          </Alert>
        ) : null}

        {added.length > 0 ? (
          <div>
            <h3 className="text-primary text-sm font-medium">Added</h3>
            <Separator className="mt-2" />
            <div className="divide-y">
              {added.map((operation) => (
                <OperationRow
                  key={operation.id}
                  checked={Boolean(checked[operation.id])}
                  onToggle={() => toggle(operation.id)}
                  orphaned={false}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{operation.testName}</p>
                    {/* Badged before the reviewer decides, not after: knowing which
                        proposals are failure cases is most of what tells them
                        whether the set is worth accepting. */}
                    {operation.kind === "negative" ? (
                      <Badge
                        variant="outline"
                        className="text-warning-foreground border-warning/60 text-xs font-normal"
                      >
                        Negative
                      </Badge>
                    ) : null}
                  </div>
                  <p className="text-muted-foreground text-sm">{operation.feature}</p>
                  {operation.expectedResult ? (
                    <p className="mt-1 text-sm">{operation.expectedResult}</p>
                  ) : null}
                  <div className="mt-2">
                    <Rationale rationale={operation.rationale} />
                  </div>
                </OperationRow>
              ))}
            </div>
          </div>
        ) : null}

        {updated.length > 0 ? (
          <div>
            <h3 className="text-muted-foreground text-sm font-medium">Changed</h3>
            <Separator className="mt-2" />
            <div className="divide-y">
              {updated.map((operation) => {
                const orphaned = isOrphaned(operation, items);
                const item = targetItem(operation, items);
                return (
                  <OperationRow
                    key={operation.id}
                    checked={Boolean(checked[operation.id])}
                    onToggle={() => toggle(operation.id)}
                    orphaned={orphaned}
                  >
                    {orphaned || !item ? (
                      <p className="text-sm">
                        This test case no longer exists — this change will be skipped
                      </p>
                    ) : (
                      <>
                        <p className="font-medium">{item.testName}</p>
                        <div className="mt-1 space-y-1">
                          {Object.entries(operation.changes ?? {}).map(
                            ([field, next]) => (
                              <p key={field} className="text-sm">
                                <span className="text-muted-foreground">
                                  {fieldLabel(field)}:{" "}
                                </span>
                                {oldFieldValue(item, field)}
                                <span className="text-muted-foreground"> → </span>
                                {next}
                              </p>
                            ),
                          )}
                        </div>
                      </>
                    )}
                    <div className="mt-2">
                      <Rationale rationale={operation.rationale} />
                    </div>
                  </OperationRow>
                );
              })}
            </div>
          </div>
        ) : null}

        {removed.length > 0 ? (
          <div>
            <h3 className="text-destructive text-sm font-medium">Removed</h3>
            <Separator className="mt-2" />
            <div className="divide-y">
              {removed.map((operation) => {
                const orphaned = isOrphaned(operation, items);
                const item = targetItem(operation, items);
                return (
                  <OperationRow
                    key={operation.id}
                    checked={Boolean(checked[operation.id])}
                    onToggle={() => toggle(operation.id)}
                    orphaned={orphaned}
                  >
                    {orphaned || !item ? (
                      <p className="text-sm">
                        This test case no longer exists — this change will be skipped
                      </p>
                    ) : (
                      <>
                        <p className="font-medium">{item.testName}</p>
                        <p className="text-muted-foreground text-sm">{item.feature}</p>
                      </>
                    )}
                    <div className="mt-2">
                      <Rationale rationale={operation.rationale} />
                    </div>
                  </OperationRow>
                );
              })}
            </div>
          </div>
        ) : null}

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
        description="Discard these proposals? Nothing will be written to the checklist."
        confirmLabel="Discard"
        isPending={discardMutation.isPending}
        error={discardMutation.error}
        onConfirm={() => discardMutation.mutate()}
      />
    </Card>
  );
}
