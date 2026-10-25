"use client";

import { useTranslations } from "next-intl";

import { Separator } from "@/components/ui/separator";
import { changeSetOperationTone, toneTextClass } from "@/lib/status";
import { cn } from "@/lib/utils";

interface OperationLike {
  op: "add" | "update" | "remove";
}

export interface OperationCounts {
  added: number;
  updated: number;
  removed: number;
}

/** What the review banner says is waiting, generic over either change-set's operation shape. */
export function countOperations<T extends OperationLike>(
  operations: T[],
): OperationCounts {
  return {
    added: operations.filter((operation) => operation.op === "add").length,
    updated: operations.filter((operation) => operation.op === "update").length,
    removed: operations.filter((operation) => operation.op === "remove").length,
  };
}

/** "3 added, 1 changed, 2 removed" -- the at-a-glance shape of a mixed change set. */
export function OperationCountsLine({ counts }: { counts: OperationCounts }) {
  const t = useTranslations("changeSets.operationCounts");
  return (
    <p className="text-muted-foreground text-sm">
      {t("summary", {
        added: counts.added,
        updated: counts.updated,
        removed: counts.removed,
      })}
    </p>
  );
}

/**
 * The Added/Changed/Removed grouping both change-set panels review operations
 * through: a headed section with a `Separator`, per kind, omitted entirely when
 * that kind is empty. Shared so the checklist and mock-data panels cannot drift on
 * *how* a mixed change set is grouped, only on what each row itself renders
 * (`docs/audit-finding-solved-logs.md` §U8.7) -- `renderRow` stays the caller's, since the
 * row content genuinely differs between a test case and a mock-data record.
 */
export function OperationGroups<T extends OperationLike>({
  operations,
  renderRow,
}: {
  operations: T[];
  renderRow: (operation: T) => React.ReactNode;
}) {
  const t = useTranslations("changeSets.operationGroups");
  const added = operations.filter((operation) => operation.op === "add");
  const updated = operations.filter((operation) => operation.op === "update");
  const removed = operations.filter((operation) => operation.op === "remove");

  return (
    <>
      {added.length > 0 ? (
        <div>
          <h3
            className={cn(
              "text-sm font-medium",
              toneTextClass(changeSetOperationTone("add")),
            )}
          >
            {t("added")}
          </h3>
          <Separator className="mt-2" />
          <div className="divide-y">{added.map(renderRow)}</div>
        </div>
      ) : null}

      {updated.length > 0 ? (
        <div>
          <h3
            className={cn(
              "text-sm font-medium",
              toneTextClass(changeSetOperationTone("update")),
            )}
          >
            {t("changed")}
          </h3>
          <Separator className="mt-2" />
          <div className="divide-y">{updated.map(renderRow)}</div>
        </div>
      ) : null}

      {removed.length > 0 ? (
        <div>
          <h3
            className={cn(
              "text-sm font-medium",
              toneTextClass(changeSetOperationTone("remove")),
            )}
          >
            {t("removed")}
          </h3>
          <Separator className="mt-2" />
          <div className="divide-y">{removed.map(renderRow)}</div>
        </div>
      ) : null}
    </>
  );
}
