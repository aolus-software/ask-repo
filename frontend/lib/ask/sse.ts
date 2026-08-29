/**
 * A parser over a fetch ReadableStream, not an EventSource: the answer endpoint is a
 * POST with a JSON body, which EventSource cannot send at all.
 *
 * Four things it must get right, each of which fails as a hang or a silently dropped
 * answer rather than an exception (design spec §9.4):
 *   - frames end at \n\n, and a network chunk can split one;
 *   - `: keep-alive` comments arrive every 15s and must be skipped, not parsed;
 *   - `data:` may span multiple lines and must be joined before JSON.parse;
 *   - an unknown event name is ignored, never fatal — M3 adds events here.
 */

export interface SseEvent {
  event: string;
  data: unknown;
}

function parseFrame(frame: string): SseEvent | null {
  let name = "message";
  const dataLines: string[] = [];

  for (const rawLine of frame.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    // A comment. `: keep-alive` is the one the backend sends; skipping is the spec
    // behaviour for every comment.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }

  if (dataLines.length === 0) return null;

  try {
    return { event: name, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    // A malformed frame is dropped and the stream continues: one bad frame must not
    // lose the answer that follows it.
    return null;
  }
}

export function createSseDecoder() {
  let buffer = "";

  function drain(): SseEvent[] {
    const events: SseEvent[] = [];

    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const event = parseFrame(frame);
      if (event) events.push(event);
      separator = buffer.indexOf("\n\n");
    }

    return events;
  }

  return {
    push(chunk: string): SseEvent[] {
      buffer += chunk;
      return drain();
    },
    /** Emit a trailing frame that arrived without its blank line. */
    flush(): SseEvent[] {
      if (!buffer.trim()) return [];
      const event = parseFrame(buffer);
      buffer = "";
      return event ? [event] : [];
    },
  };
}

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const textDecoder = new TextDecoder();
  const decoder = createSseDecoder();

  try {
    for (;;) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decoder.push(textDecoder.decode(value, { stream: true }))) {
        yield event;
      }
    }
    for (const event of decoder.flush()) yield event;
  } finally {
    reader.releaseLock();
  }
}
