import type { FeedbackReasonCode, FeedbackTargetType } from "@/lib/api/types";

/** Mirrors `app/core/feedback.py`'s applicability map. The server is the check. */
const MESSAGE_REASONS: FeedbackReasonCode[] = [
  "wrong_file_cited",
  "missed_something",
  "invented_something",
  "right_but_unusable",
  "wrong_language_or_tone",
  "other",
];

const CHANGE_SET_REASONS: FeedbackReasonCode[] = [
  "missed_something",
  "invented_something",
  "duplicate_or_redundant",
  "wrong_scope",
  "right_but_unusable",
  "other",
];

export const REASON_LABELS: Record<FeedbackReasonCode, string> = {
  wrong_file_cited: "Cited the wrong file",
  missed_something: "Missed something in the repo",
  invented_something: "Invented something",
  right_but_unusable: "Right, but not usable",
  wrong_language_or_tone: "Wrong language or tone",
  duplicate_or_redundant: "Duplicate or redundant",
  wrong_scope: "Wrong scope",
  other: "Something else",
};

export function reasonsFor(targetType: FeedbackTargetType): FeedbackReasonCode[] {
  return targetType.endsWith("_change_set") ? CHANGE_SET_REASONS : MESSAGE_REASONS;
}

export const NOTE_MAX_LENGTH = 500;

export const NOTE_DISCLOSURE =
  "Administrators can read this note. It is never sent to the AI model.";
