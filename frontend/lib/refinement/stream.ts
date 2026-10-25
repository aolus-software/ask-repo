import { parseSseStream } from "@/lib/ask/sse";
import type {
  CitationPayload,
  DoneEventPayload,
  ErrorEventPayload,
  FinishReason,
  StatusEventPayload,
} from "@/lib/api/types";

/**
 * The one event that differs between the two refinement chats: the checklist chat
 * streams `changeSet`, the mock-data chat `mockDataChangeSet`
 * (`.claude/rules/rag.md`, "The ordering contract holds on both refinement chats too").
 */
export type ChangeSetEventName = "changeSet" | "mockDataChangeSet";

export interface RefinementStreamHandlers<TChangeSet> {
  onCitations: (citations: CitationPayload[]) => void;
  onToken: (text: string) => void;
  onChangeSet: (changeSet: TChangeSet) => void;
  /** The same `status` phase the Ask screen shows (`docs/audit-finding-solved-logs.md` §U8.2). */
  onPhase?: (phase: string) => void;
}

export interface RefinementTurnResult<TChangeSet> {
  content: string;
  changeSet: TChangeSet | null;
  done: DoneEventPayload | null;
  error: ErrorEventPayload | null;
  /** The terminator's `finishReason`, whichever of `done` or `error` arrived; null when neither did. */
  finishReason: FinishReason | null;
}

/**
 * Consume one refinement turn, for either chat: `changeSetEvent` names the change-set
 * event this chat's route emits.
 *
 * The SSE parser itself is reused unchanged from the Ask screen — the wire format is
 * the same contract, and a second parser would be a second place the frame-splitting
 * and keep-alive rules could be got wrong. Both chats share this reader for the same
 * reason: a fix to terminator handling lands once.
 *
 * Exactly one terminator arrives, `done` or `error`, and both carry a `finishReason`.
 * An unrecognised event name — including the other chat's change-set event — is
 * ignored rather than fatal: the backend adds events over time and an old tab must
 * not break on a new one.
 */
export async function consumeRefinementStream<TChangeSet>(
  response: Response,
  changeSetEvent: ChangeSetEventName,
  handlers: RefinementStreamHandlers<TChangeSet>,
): Promise<RefinementTurnResult<TChangeSet>> {
  const result: RefinementTurnResult<TChangeSet> = {
    content: "",
    changeSet: null,
    done: null,
    error: null,
    finishReason: null,
  };
  if (!response.body) return result;

  for await (const event of parseSseStream(response.body)) {
    switch (event.event) {
      case "status":
        handlers.onPhase?.((event.data as StatusEventPayload).phase);
        break;
      case "citations":
        handlers.onCitations(
          (event.data as { citations: CitationPayload[] }).citations,
        );
        break;
      case "token": {
        const { text } = event.data as { text: string };
        result.content += text;
        handlers.onToken(text);
        break;
      }
      case changeSetEvent:
        result.changeSet = event.data as TChangeSet;
        handlers.onChangeSet(result.changeSet);
        break;
      case "done":
        result.done = event.data as DoneEventPayload;
        result.finishReason = result.done.finishReason;
        break;
      case "error":
        result.error = event.data as ErrorEventPayload;
        result.finishReason = result.error.finishReason;
        break;
      default:
        // Anything added later. Ignored deliberately.
        break;
    }
  }

  return result;
}
