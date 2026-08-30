/**
 * Carries the first question across the one navigation between creating a
 * conversation and asking in it (design spec §9.3).
 *
 * A module-level map rather than sessionStorage: the value lives for one navigation
 * and must not survive a reload. A hard reload in that window loses the question,
 * which is correct — the backend persisted nothing either.
 */
const pending = new Map<string, string>();

export function setPendingQuestion(conversationId: string, question: string): void {
  pending.set(conversationId, question);
}

/** Reads and removes: a question must be asked exactly once. */
export function takePendingQuestion(conversationId: string): string | undefined {
  const question = pending.get(conversationId);
  pending.delete(conversationId);
  return question;
}
