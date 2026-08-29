"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";

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
      <pre className="bg-muted overflow-x-auto rounded-md p-4 font-mono text-sm">{children}</pre>
    </div>
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
export function Answer({ content }: { content: string }) {
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
              <code className="bg-muted rounded px-1 py-0.5 font-mono text-sm">{children}</code>
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
    </div>
  );
}
