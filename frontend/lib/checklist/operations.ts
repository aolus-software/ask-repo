import type { ChangeOperation, ChecklistItemResponse } from "@/lib/api/types";

export interface FeatureGroup {
  feature: string;
  items: ChecklistItemResponse[];
}

/**
 * The grid, grouped by feature. Pure, so the grouping is tested without React and the
 * grid component computes nothing.
 *
 * Features keep first-appearance order rather than being sorted alphabetically: the
 * backend already returns items ordered by (feature, position), and re-sorting here
 * would silently disagree with the export's order — which is the order a tester works.
 */
export function groupByFeature(items: ChecklistItemResponse[]): FeatureGroup[] {
  const groups = new Map<string, ChecklistItemResponse[]>();
  for (const item of items) {
    const bucket = groups.get(item.feature);
    if (bucket) bucket.push(item);
    else groups.set(item.feature, [item]);
  }
  return [...groups.entries()].map(([feature, rows]) => ({
    feature,
    items: [...rows].sort((left, right) => left.position - right.position),
  }));
}

export interface OperationCounts {
  added: number;
  updated: number;
  removed: number;
}

/** What the review banner says is waiting, without re-reading the change set's prose. */
export function summariseOperations(operations: ChangeOperation[]): OperationCounts {
  return {
    added: operations.filter((operation) => operation.op === "add").length,
    updated: operations.filter((operation) => operation.op === "update").length,
    removed: operations.filter((operation) => operation.op === "remove").length,
  };
}
