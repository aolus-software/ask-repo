"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ChecklistItemResponse, ChecklistItemStatus } from "@/lib/api/types";

/**
 * `blocked` is spelled out because a tester who cannot find the value records a
 * blocked test as a failure, and the pass rate stops meaning anything.
 */
const STATUS_LABELS: Record<ChecklistItemStatus, string> = {
  untested: "Untested",
  pass: "Pass",
  fail: "Fail",
  blocked: "Blocked — could not run",
};

const STATUS_ORDER: ChecklistItemStatus[] = ["untested", "pass", "fail", "blocked"];

/**
 * The ungated write: what a tester observed, and the verdict they reached.
 *
 * Both controls are always enabled, for every user, on every row. That is the whole
 * point of the split (spec 2.5) — a tester must be able to record what they saw
 * without being able to rewrite what was expected, because otherwise the cheapest way
 * to make a failing test pass is to edit the expectation.
 *
 * Presentational on purpose. It calls `onSave` and owns no mutation, so the grid can
 * apply one optimistic update across the rows a tester works down, and so this
 * component can be rendered in a test without a query client.
 */
export function ResultCell({
  item,
  onSave,
  canEditDefinition,
  isSaving = false,
}: {
  item: ChecklistItemResponse;
  onSave: (input: {
    currentResult: string | null;
    status: ChecklistItemStatus;
  }) => void;
  canEditDefinition: boolean;
  isSaving?: boolean;
}) {
  // Seeded from the row and never prefilled with a suggestion: AskRepo has not run the
  // application, so an untested row shows an empty observation (spec 2.3).
  const [currentResult, setCurrentResult] = useState(item.currentResult ?? "");
  const [status, setStatus] = useState<ChecklistItemStatus>(item.status);

  const isDirty =
    currentResult !== (item.currentResult ?? "") || status !== item.status;

  return (
    <div className="flex min-w-64 flex-col gap-3">
      <Field>
        <FieldLabel htmlFor={`result-${item.id}`}>Current result</FieldLabel>
        <Textarea
          id={`result-${item.id}`}
          placeholder="What happened when you ran this?"
          value={currentResult}
          onChange={(event) => setCurrentResult(event.target.value)}
          className="min-h-20"
        />
      </Field>

      <Field>
        <FieldLabel htmlFor={`status-${item.id}`}>Status</FieldLabel>
        <Select
          value={status}
          onValueChange={(value) => setStatus(value as ChecklistItemStatus)}
        >
          <SelectTrigger id={`status-${item.id}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_ORDER.map((value) => (
              <SelectItem key={value} value={value}>
                {STATUS_LABELS[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {canEditDefinition ? null : (
        <p className="text-muted-foreground text-xs">
          You can record a result on any test case, including ones you did not write.
        </p>
      )}

      <Button
        size="sm"
        disabled={!isDirty || isSaving}
        onClick={() =>
          onSave({ currentResult: currentResult === "" ? null : currentResult, status })
        }
      >
        {isSaving ? "Saving…" : "Save result"}
      </Button>
    </div>
  );
}
