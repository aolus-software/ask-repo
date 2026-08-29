"use client";

import { ChevronDown } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { CitationPayload } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * All retrieved spans, with the cited ones marked.
 *
 * The `citations` event carries `cited: null` — it is emitted before generation and
 * cannot know what the model will use. `done.citedIndexes` says which were actually
 * used, and the stored message carries resolved flags after the refetch.
 */
export function Sources({
  citations,
  citedIndexes,
}: {
  citations: CitationPayload[];
  citedIndexes: number[];
}) {
  if (citations.length === 0) return null;

  const isCited = (citation: CitationPayload) =>
    citation.cited ?? citedIndexes.includes(citation.index);

  return (
    <Collapsible className="mt-4">
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-sm font-medium">
        <ChevronDown className="size-4" />
        Sources ({citations.length})
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-2 space-y-1">
          {citations.map((citation) => (
            <li
              key={citation.index}
              id={`citation-${citation.index}`}
              className={cn(
                "border-border rounded-md border p-2 font-mono text-sm",
                isCited(citation) ? "bg-accent" : "text-muted-foreground",
              )}
            >
              <span className="font-semibold">[{citation.index}]</span> {citation.filePath}
              <span className="text-muted-foreground">
                {" "}
                lines {citation.startLine}–{citation.endLine}
                {citation.symbol ? ` · ${citation.symbol}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
