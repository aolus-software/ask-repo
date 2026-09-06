import { parseSseStream } from "@/lib/ask/sse";
import type {
  CitationPayload,
  DoneEventPayload,
  ErrorEventPayload,
  MockDataChangeSetEventPayload,
} from "@/lib/api/types";

export interface MockDataStreamHandlers {
  onCitations: (citations: CitationPayload[]) => void;
  onToken: (text: string) => void;
  onChangeSet: (changeSet: MockDataChangeSetEventPayload) => void;
}

export interface MockDataTurnResult {
  content: string;
  changeSet: MockDataChangeSetEventPayload | null;
  done: DoneEventPayload | null;
  error: ErrorEventPayload | null;
}

/**
 * Consume one mock-data refinement turn. Structurally identical to
 * `consumeChecklistStream` -- same SSE parser, same ordering contract -- for the
 * `mockDataChangeSet` event instead of `changeSet`.
 */
export async function consumeMockDataStream(
  response: Response,
  handlers: MockDataStreamHandlers,
): Promise<MockDataTurnResult> {
  const result: MockDataTurnResult = {
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
      case "mockDataChangeSet":
        result.changeSet = event.data as MockDataChangeSetEventPayload;
        handlers.onChangeSet(result.changeSet);
        break;
      case "done":
        result.done = event.data as DoneEventPayload;
        break;
      case "error":
        result.error = event.data as ErrorEventPayload;
        break;
      default:
        break;
    }
  }

  return result;
}
