"use client";

import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDeleteMockDataRecord } from "@/hooks/use-mock-data-mutations";
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

export function RecordsTable({
  moduleId,
  records,
}: {
  moduleId: string;
  records: MockDataRecordResponse[];
}) {
  const deleteRecord = useDeleteMockDataRecord(moduleId);
  const columns = columnsFor(records);

  if (records.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No mock data yet. Generate a batch, or ask for one by chat.
      </p>
    );
  }

  return (
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
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete record"
                disabled={deleteRecord.isPending}
                onClick={() => deleteRecord.mutate(record.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
