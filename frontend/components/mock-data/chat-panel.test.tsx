import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockDataChatPanel } from "@/components/mock-data/chat-panel";

const { apiFetch, apiFetchRaw } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiFetchRaw: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ apiFetch, apiFetchRaw }));

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  return {
    body: new ReadableStream({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    }),
  } as Response;
}

function renderPanel(canSend: boolean | null = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MockDataChatPanel
        moduleId="m1"
        hasPendingChangeSet={false}
        isGenerating={false}
        canSend={canSend}
      />
    </QueryClientProvider>,
  );
}

async function ask(question: string) {
  fireEvent.change(screen.getByLabelText(/your question/i), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: /^ask$/i }));
}

describe("MockDataChatPanel terminal states", () => {
  afterEach(() => vi.clearAllMocks());

  it("shows the quiet interrupted note, not a destructive Alert, when the stream ends with no terminator", async () => {
    // Never resolves: the note is gated on `!reconciled`, and reconciliation is the
    // very refetch this same mock backs — leaving it pending is what keeps the
    // assertion below deterministic instead of racing the reconciliation flip.
    apiFetch.mockImplementation(() => new Promise(() => {}));
    apiFetchRaw.mockResolvedValue(
      sseResponse(['event: token\ndata: {"text":"partial"}\n\n']),
    );
    renderPanel();

    await ask("what changed?");

    expect(
      await screen.findByText("The connection dropped. What arrived above is kept."),
    ).toBeInTheDocument();
    expect(screen.queryByText("The reply stopped")).toBeNull();
  });

  it("shows the destructive Alert for a real error terminator", async () => {
    apiFetch.mockResolvedValue([]);
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: error\ndata: {"messageId":"m1","code":"LLM_UNAVAILABLE","message":"The model is unavailable.","finishReason":"error"}\n\n',
      ]),
    );
    renderPanel();

    await ask("what changed?");

    expect(await screen.findByText("The reply stopped")).toBeInTheDocument();
    expect(await screen.findByText("The model is unavailable.")).toBeInTheDocument();
    expect(
      screen.queryByText("The connection dropped. What arrived above is kept."),
    ).toBeNull();
  });

  it("shows neither note for a normal done terminator", async () => {
    apiFetch.mockResolvedValue([]);
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"ok"}\n\n',
        'event: done\ndata: {"messageId":"m1","model":"qwen","finishReason":"stop","citedIndexes":[],"groundingWarnings":[]}\n\n',
      ]),
    );
    renderPanel();

    await ask("what changed?");

    await waitFor(() =>
      expect(apiFetchRaw).toHaveBeenCalledWith(
        expect.stringContaining("/checklist-modules/m1/mock-data-messages"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(screen.queryByText("The reply stopped")).toBeNull();
    expect(
      screen.queryByText("The connection dropped. What arrived above is kept."),
    ).toBeNull();
  });
});

describe("finishReason handling", () => {
  afterEach(() => vi.clearAllMocks());

  it("shows the ended-early note for a timeout and resends the last question on Try again", async () => {
    apiFetch.mockImplementation(() => new Promise(() => {}));
    apiFetchRaw.mockImplementation(async () =>
      sseResponse([
        'event: token\ndata: {"text":"partial"}\n\n',
        'event: done\ndata: {"messageId":"m1","model":"x","finishReason":"timeout","citedIndexes":[],"groundingWarnings":[]}\n\n',
      ]),
    );
    renderPanel();

    await ask("why did it time out?");

    expect(
      await screen.findByText("This answer ended early (timeout)."),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    await waitFor(() => expect(apiFetchRaw).toHaveBeenCalledTimes(2));
    expect(apiFetchRaw).toHaveBeenLastCalledWith(
      expect.stringContaining("/checklist-modules/m1/mock-data-messages"),
      expect.objectContaining({
        body: JSON.stringify({ question: "why did it time out?" }),
      }),
    );
  });

  it("offers Try again on a timeout error terminator", async () => {
    apiFetch.mockResolvedValue([]);
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: error\ndata: {"messageId":"m1","code":"LLM_UNAVAILABLE","message":"Too slow.","finishReason":"timeout"}\n\n',
      ]),
    );
    renderPanel();

    await ask("slow one");

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });

  it("shows neither the note nor Try again for a normal finish", async () => {
    apiFetch.mockImplementation(() => new Promise(() => {}));
    apiFetchRaw.mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text":"ok"}\n\n',
        'event: done\ndata: {"messageId":"m1","model":"x","finishReason":"stop","citedIndexes":[],"groundingWarnings":[]}\n\n',
      ]),
    );
    renderPanel();

    await ask("fine");

    await waitFor(() => expect(apiFetchRaw).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.queryByText(/ended early/i)).toBeNull();
  });
});

describe("composer permission wording", () => {
  afterEach(() => vi.clearAllMocks());

  it("blocks sending with no permission text while permissions are not yet known", () => {
    apiFetch.mockResolvedValue([]);
    renderPanel(null);

    const box = screen.getByLabelText(/your question/i);
    fireEvent.change(box, { target: { value: "typed" } });
    expect(screen.getByRole("button", { name: /^ask$/i })).toBeDisabled();
    expect(box.getAttribute("placeholder") ?? "").not.toMatch(/permission/i);
  });

  it("names the missing permission once permissions are known to lack it", () => {
    apiFetch.mockResolvedValue([]);
    renderPanel(false);

    const box = screen.getByLabelText(/your question/i);
    fireEvent.change(box, { target: { value: "typed" } });
    expect(screen.getByRole("button", { name: /^ask$/i })).toBeDisabled();
    expect(box.getAttribute("placeholder")).toMatch(/do not have permission/i);
  });
});
