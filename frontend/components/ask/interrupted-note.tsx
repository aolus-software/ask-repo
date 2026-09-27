/**
 * The quiet note shown when a stream ends with no terminator — a client disconnect,
 * persisted server-side with `finishReason: "disconnected"` (`.claude/rules/rag.md`).
 * Nothing failed, so this is not an `Alert`: the Ask screen, the checklist's
 * refinement chat and the mock-data refinement chat all render the identical
 * sentence, from here, so the three surfaces cannot drift onto three different
 * wordings for the same benign event (`docs/audit-finding-solved-logs.md` §U8.6).
 */
export const INTERRUPTED_MESSAGE =
  "The connection dropped. What arrived above is kept.";

export function InterruptedNote() {
  return <p className="text-muted-foreground mt-2 text-xs">{INTERRUPTED_MESSAGE}</p>;
}
