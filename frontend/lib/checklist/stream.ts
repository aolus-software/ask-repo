import { parseSseStream } from "@/lib/ask/sse";
import type {
  ChangeSetEventPayload,
  CitationPayload,
  DoneEventPayload,
  ErrorEventPayload,
} from "@/lib/api/types";

export interface ChecklistStreamHandlers {
  onCitations: (citations: CitationPayload[]) => void;
  onToken: (text: string) => void;
  onChangeSet: (changeSet: ChangeSetEventPayload) => void;
}

export interface ChecklistTurnResult {
  content: string;
  changeSet: ChangeSetEventPayload | null;
  done: DoneEventPayload | null;
  error: ErrorEventPayload | null;
}

/**
 * Consume one refinement turn.
 *
 * The SSE parser itself is reused unchanged from the Ask screen — the wire format is
 * the same contract, and a second parser would be a second place the frame-splitting
 * and keep-alive rules could be got wrong.
 *
 * Exactly one terminator arrives, `done` or `error`, and both carry a `finishReason`.
 * An unrecognised event name is ignored rather than fatal: the backend adds events
 * over time and an old tab must not break on a new one.
 */
export async function consumeChecklistStream(
  response: Response,
  handlers: ChecklistStreamHandlers,
): Promise<ChecklistTurnResult> {
  const result: ChecklistTurnResult = {
    content: "",
    changeSet: null,
    done: null,
    error: null,
  };
  if (!response.body) return result;

  for await (const event of parseSseStream(response.body)) {
    switch (event.event) {
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
      case "changeSet":
        result.changeSet = event.data as ChangeSetEventPayload;
        handlers.onChangeSet(result.changeSet);
        break;
      case "done":
        result.done = event.data as DoneEventPayload;
        break;
      case "error":
        result.error = event.data as ErrorEventPayload;
        break;
      default:
        // `status`, and anything added later. Ignored deliberately.
        break;
    }
  }

  return result;
}
