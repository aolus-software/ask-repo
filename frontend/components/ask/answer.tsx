"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SaveToQADialog } from "@/components/qa/save-to-qa-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { FinishReason } from "@/lib/api/types";

function CodeBlock({ children }: { children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Copy code"
        className="absolute top-2 right-2"
        onClick={(event) => {
          const pre = event.currentTarget.parentElement?.querySelector("pre");
          void navigator.clipboard.writeText(pre?.textContent ?? "");
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </Button>
      <pre className="bg-muted overflow-x-auto rounded-md p-4 font-mono text-sm">
        {children}
      </pre>
    </div>
  );
}

/**
 * Save to QA List, shown only when the caller passes a `messageId` — which
 * `MessageList` does only for a stored assistant message, never for a message
 * still streaming or a QA pair's own result (`components/qa/rerun-panel.tsx`,
 * `app/(app)/qa/[id]/qa-pair-screen.tsx`), neither of which has a message to
 * publish from.
 *
 * Enabled only when `finishReason === "stop"`, disabled otherwise with a
 * tooltip explaining why: this mirrors the server's `409 ANSWER_INCOMPLETE`
 * before the request rather than after it. The server check is the one that
 * has to be right — it is the only enforcement point, because a request body
 * cannot be trusted to say honestly whether it was cut off
 * (`docs/superpowers/specs/2026-08-31-m4-qa-list-design.md` §2.6). This one
 * only has to be kind: it saves a click that the server would refuse anyway.
 */
function SaveToQAAction({
  messageId,
  finishReason,
}: {
  messageId: string;
  finishReason: FinishReason | null;
}) {
  const [open, setOpen] = useState(false);
  const canSave = finishReason === "stop";

  return (
    <>
      <Tooltip>
        <TooltipTrigger render={<span className="inline-block" />}>
          {canSave ? (
            <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
              Save to QA List
            </Button>
          ) : (
            <Button variant="outline" size="sm" disabled>
              Save to QA List
            </Button>
          )}
        </TooltipTrigger>
        <TooltipContent>
          {canSave
            ? "Publish this answer to the shared QA List."
            : "This answer did not finish, so it cannot be published to the team."}
        </TooltipContent>
      </Tooltip>
      <SaveToQADialog messageId={messageId} open={open} onOpenChange={setOpen} />
    </>
  );
}

/**
 * Markdown only — no rehype-raw, no dangerouslySetInnerHTML, anywhere.
 *
 * Retrieved excerpts are untrusted input written by anyone with commit access to an
 * indexed repository (docs/PRD.md §9), and the answer can quote them verbatim.
 * Rendering raw HTML would turn a comment in someone's repo into markup in the
 * operator's browser — converting a prompt-injection attempt, which can only make the
 * model SAY something wrong, into something that can DO something in the client. That
 * is the architectural bound §9 relies on, given away at the last render step.
 *
 * No syntax highlighter: shiki is a large dependency for a first pass, and a plain
 * mono block is honest about what it is.
 */
export function Answer({
  content,
  messageId,
  finishReason,
}: {
  content: string;
  /** The stored message this answer came from. Omit for a streaming or a QA
   * pair answer — neither is a message that can be published. */
  messageId?: string;
  finishReason?: FinishReason | null;
}) {
  return (
    <div className="space-y-4 text-base leading-7">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          code: ({ children, className }) =>
            className ? (
              <code className={className}>{children}</code>
            ) : (
              <code className="bg-muted rounded px-1 py-0.5 font-mono text-sm">
                {children}
              </code>
            ),
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-primary underline"
              rel="noreferrer noopener"
              target="_blank"
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </Markdown>
      {messageId ? (
        <SaveToQAAction messageId={messageId} finishReason={finishReason ?? null} />
      ) : null}
    </div>
  );
}
