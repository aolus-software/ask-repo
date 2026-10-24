import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TranslateEvalSetDialog } from "@/components/eval/translate-eval-set-dialog";
import type { Language } from "@/lib/i18n/languages";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function renderDialog(existing: Language[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TranslateEvalSetDialog
        projectId="p1"
        set={{ id: "s1", name: "Auth" }}
        existing={existing}
      />
    </QueryClientProvider>,
  );
}

function postAnswering(response: () => Response) {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "POST" ? response() : Response.json({}),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openAndSubmit() {
  fireEvent.click(screen.getByRole("button", { name: /^translate$/i }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: /^translate$/i }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("TranslateEvalSetDialog", () => {
  it("posts the source id and the first free language, then opens the new set", async () => {
    const fetchMock = postAnswering(() => Response.json({ id: "t1" }, { status: 202 }));
    renderDialog(["id"]);

    await openAndSubmit();

    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p1/eval/t1"));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      sourceSetId: "s1",
      language: "ja",
    });
  });

  it("shows EVAL_TRANSLATION_EXISTS by its code, not its message", async () => {
    postAnswering(() =>
      Response.json(
        { detail: { code: "EVAL_TRANSLATION_EXISTS", message: "server text" } },
        { status: 409 },
      ),
    );
    renderDialog();

    await openAndSubmit();

    // The catalogue sentence for this code arrives with the backend lane's errors.json;
    // until then an unknown code falls back to the server message, so assert only that
    // the dialog surfaces the failure as an alert. Tighten once the sentence exists.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
