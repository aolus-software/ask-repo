"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSetPairExcluded } from "@/hooks/use-eval";
import type { EvalPair } from "@/lib/api/types";

/** A set's questions. The reference answer expands in place; excluding is `eval.run` only. */
export function EvalPairTable({
  setId,
  pairs,
  canRun,
}: {
  setId: string;
  pairs: EvalPair[];
  canRun: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const setExcluded = useSetPairExcluded(setId);

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Question</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Source</TableHead>
            {canRun ? <TableHead>Excluded</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pairs.map((pair) => {
            const expanded = open === pair.id;
            return (
              <Fragment key={pair.id}>
                <TableRow
                  className={pair.excluded ? "text-muted-foreground" : undefined}
                >
                  <TableCell className="max-w-xl whitespace-normal">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      className="hover:text-primary flex items-start gap-2 text-left"
                      onClick={() => setOpen(expanded ? null : pair.id)}
                    >
                      {expanded ? (
                        <ChevronDown className="mt-0.5 size-4 shrink-0" />
                      ) : (
                        <ChevronRight className="mt-0.5 size-4 shrink-0" />
                      )}
                      {pair.question}
                    </button>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{pair.questionType}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground font-mono text-sm">
                    {pair.sourceFile}:{pair.startLine}-{pair.endLine}
                  </TableCell>
                  {canRun ? (
                    <TableCell>
                      <Switch
                        aria-label={`Exclude: ${pair.question}`}
                        checked={pair.excluded}
                        onCheckedChange={(checked) =>
                          setExcluded.mutate({ pairId: pair.id, excluded: checked })
                        }
                      />
                    </TableCell>
                  ) : null}
                </TableRow>
                {expanded ? (
                  <TableRow>
                    <TableCell
                      colSpan={canRun ? 4 : 3}
                      className="bg-muted/40 text-sm whitespace-pre-wrap"
                    >
                      <p className="text-muted-foreground mb-1 text-xs font-medium">
                        Reference answer
                      </p>
                      {pair.referenceAnswer}
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
