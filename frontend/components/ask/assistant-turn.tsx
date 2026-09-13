import { Sparkles } from "lucide-react";

/**
 * The assistant's role icon and layout, shared between a persisted message
 * (`MessageList`) and the live in-flight turn on all three streaming surfaces — Ask,
 * the checklist chat, the mock-data chat — so "answering" looks like "answered"
 * rather than the reply gaining a visual anchor only once it lands
 * (`.claude/rules/rag.md`: one `Answerer`, one visual language).
 */
export function AssistantTurn({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full">
        <Sparkles className="size-4" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
