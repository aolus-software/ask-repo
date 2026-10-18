"use client";

import { Database, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/feedback/empty-state";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDeleteMockDataRecord } from "@/hooks/use-mock-data-mutations";
import { useErrorText } from "@/lib/i18n/error-text";
import type { MockDataRecordResponse } from "@/lib/api/types";

/** Every field key across every record, first-seen order -- the columns are dynamic
 * because the schema they came from is whatever the module's code actually defines. */
function columnsFor(records: MockDataRecordResponse[]): string[] {
  const seen: string[] = [];
  for (const record of records) {
    for (const key of Object.keys(record.fields)) {
      if (!seen.includes(key)) seen.push(key);
    }
  }
  return seen;
}

function DeleteRecordButton({ moduleId, id }: { moduleId: string; id: string }) {
  const t = useTranslations("mockData.recordsTable");
  const errorText = useErrorText();
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteMockDataRecord(moduleId);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("deleteAria")}
        onClick={() => setConfirming(true)}
      >
        <Trash2 className="size-4" />
      </Button>
      {/* Every other destructive action in the app confirms first — this was the one
          exception (`docs/audit-finding-solved-logs.md` §U5.1). */}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("deleteTitle")}
        description={t("deleteDescription")}
        confirmLabel={t("delete")}
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() =>
          remove.mutate(id, {
            onSuccess: () => {
              toast.success(t("deleted"));
              setConfirming(false);
            },
            onError: (error) => {
              toast.error(errorText(error));
            },
          })
        }
      />
    </>
  );
}

export function RecordsTable({
  moduleId,
  records,
  canEdit,
  isGenerating,
}: {
  moduleId: string;
  records: MockDataRecordResponse[];
  /** While a generation runs the empty state must not invite starting another. */
  isGenerating: boolean;
  /** Mirrors the backend's `mockdata.edit` gate; it does not replace it. */
  canEdit: boolean;
}) {
  const t = useTranslations("mockData.recordsTable");
  const columns = columnsFor(records);

  // Every table sits inside a Card — `.claude/rules/design-system.md` §11 — so this
  // one no longer shows the page background through it the way it did before.
  if (records.length === 0) {
    return (
      <Card className="p-0">
        <EmptyState
          icon={Database}
          title={isGenerating ? t("generatingTitle") : t("emptyTitle")}
          description={
            isGenerating ? t("generatingDescription") : t("emptyDescription")
          }
        />
      </Card>
    );
  }

  return (
    <Card className="p-0">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column}>{column}</TableHead>
              ))}
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {records.map((record) => (
              <TableRow key={record.id}>
                {columns.map((column) => (
                  <TableCell key={column}>{record.fields[column] ?? "—"}</TableCell>
                ))}
                <TableCell>
                  {canEdit ? (
                    <DeleteRecordButton moduleId={moduleId} id={record.id} />
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Card>
  );
}
