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

/** Every reason code, in display order. The words live in `outputFeedback.reasons`. */
export const REASON_CODES: FeedbackReasonCode[] = [
  "wrong_file_cited",
  "missed_something",
  "invented_something",
  "right_but_unusable",
  "wrong_language_or_tone",
  "duplicate_or_redundant",
  "wrong_scope",
  "other",
];

export function reasonsFor(targetType: FeedbackTargetType): FeedbackReasonCode[] {
  return targetType.endsWith("_change_set") ? CHANGE_SET_REASONS : MESSAGE_REASONS;
}

export const NOTE_MAX_LENGTH = 500;
