/**
 * One wording for "what is the model doing right now", shared by all three streaming
 * surfaces — Ask, the checklist refinement chat, and the mock-data refinement chat are
 * three callers of the same graph, not three features (`.claude/rules/rag.md`), and
 * only one of them showed this before (`docs/ui-audit-findings.md` §U8.2).
 */
export const PHASE_LABELS: Record<string, string> = {
  queued: "Queued…",
  classifying: "Understanding the question…",
  retrieving: "Searching the codebase…",
  grading: "Checking what it found…",
  generating: "Writing the answer…",
};
