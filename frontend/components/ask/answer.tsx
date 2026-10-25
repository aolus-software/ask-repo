"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";

function CodeBlock({ children }: { children: React.ReactNode }) {
  const t = useTranslations("ask");
  const [copied, setCopied] = useState(false);

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("answer.copyCode")}
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
              <code className="bg-muted rounded px-1 py-1 font-mono text-sm">
                {children}
              </code>
            ),
          // Tailwind's reset strips list markers, heading sizes and table borders, and
          // there is deliberately no typography plugin, so each element is given the
          // documented type scale here (`docs/design.md` -> Typography).
          h1: ({ children }) => (
            <h1 className="text-xl font-semibold tracking-tight">{children}</h1>
          ),
          h2: ({ children }) => <h2 className="text-xl font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold">{children}</h3>,
          h4: ({ children }) => <h4 className="text-base font-semibold">{children}</h4>,
          h5: ({ children }) => <h5 className="text-sm font-semibold">{children}</h5>,
          h6: ({ children }) => (
            <h6 className="text-muted-foreground text-sm font-semibold">{children}</h6>
          ),
          ul: ({ children }) => (
            <ul className="list-disc space-y-1 pl-6">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-1 pl-6">{children}</ol>
          ),
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-border text-muted-foreground border-l-4 pl-4">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="border-border" />,
          // The scroll container sits around the table so a wide one never makes the
          // page scroll sideways.
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
          tr: ({ children }) => <tr className="border-border border-b">{children}</tr>,
          th: ({ children }) => (
            <th className="px-3 py-2 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => <td className="px-3 py-2 align-top">{children}</td>,
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
