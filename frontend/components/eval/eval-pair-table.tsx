"use client";

import { ChevronDown, ChevronRight, FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { Answer } from "@/components/ask/answer";
import { EmptyState } from "@/components/feedback/empty-state";
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
import { useErrorText } from "@/lib/i18n/error-text";
import { isApiError } from "@/lib/api/errors";
import type { EvalPair } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** A set's questions. The reference answer expands in place; excluding is `eval.run` only. */
export function EvalPairTable({
  setId,
  pairs,
  canRun,
  generating = false,
}: {
  setId: string;
  pairs: EvalPair[];
  canRun: boolean;
  /** The set is still being generated, so no pairs yet is expected rather than empty. */
  generating?: boolean;
}) {
  const t = useTranslations("eval.pairTable");
  const unfaithfulLabel = useTranslations("eval")("unfaithful");
  const tType = useTranslations("eval.questionTypes");
  const errorText = useErrorText();
  const [open, setOpen] = useState<string | null>(null);
  const setExcluded = useSetPairExcluded(setId);

  if (pairs.length === 0) {
    return (
      <EmptyState
        icon={FlaskConical}
        title={generating ? t("generatingTitle") : t("emptyTitle")}
        description={generating ? t("generatingDescription") : t("emptyDescription")}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("columns.question")}</TableHead>
            <TableHead>{t("columns.type")}</TableHead>
            <TableHead>{t("columns.source")}</TableHead>
            {canRun ? <TableHead>{t("columns.excluded")}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pairs.map((pair) => {
            const expanded = open === pair.id;
            return (
              <Fragment key={pair.id}>
                <TableRow
                  className={cn(
                    pair.excluded && "text-muted-foreground",
                    expanded && "bg-muted/50 border-b-0",
                  )}
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
                      <span>
                        {pair.question}
                        {pair.exclusionReason === "translation_unfaithful" ? (
                          <span className="text-warning mt-1 block text-xs">
                            {unfaithfulLabel}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{tType(pair.questionType)}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground font-mono text-sm">
                    {pair.sourceFile}:{pair.startLine}-{pair.endLine}
                  </TableCell>
                  {canRun ? (
                    <TableCell>
                      <Switch
                        aria-label={t("excludeLabel", { question: pair.question })}
                        checked={pair.excluded}
                        onCheckedChange={(checked) =>
                          setExcluded.mutate(
                            { pairId: pair.id, excluded: checked },
                            {
                              onError: (error) =>
                                toast.error(
                                  isApiError(error)
                                    ? errorText(error)
                                    : t("saveFailed"),
                                ),
                            },
                          )
                        }
                      />
                    </TableCell>
                  ) : null}
                </TableRow>
                {expanded ? (
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableCell
                      colSpan={canRun ? 4 : 3}
                      className="pt-0 pb-4 whitespace-normal"
                    >
                      {/* Inset under the question text (chevron + gap) and capped at a
                          readable line length; a full-width paragraph is hard to follow. */}
                      <div className="border-primary bg-card ml-6 max-w-prose rounded-md border-l-2 px-4 py-3">
                        <p className="text-muted-foreground mb-1.5 text-xs font-medium tracking-wide uppercase">
                          {t("referenceAnswer")}
                        </p>
                        <Answer content={pair.referenceAnswer} />
                      </div>
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
