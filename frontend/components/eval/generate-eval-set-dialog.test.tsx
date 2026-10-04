import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GenerateEvalSetDialog } from "@/components/eval/generate-eval-set-dialog";
import { PERMISSION } from "@/lib/can";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderDialog(permissions: string[] = [PERMISSION.EVAL_RUN]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GenerateEvalSetDialog projectId="p1" permissions={permissions} />
    </QueryClientProvider>,
  );
}

function pathsOrPost(onPost: (init: RequestInit) => Response) {
  return vi.fn(async (url: string, init?: RequestInit) =>
    init?.method === "POST"
      ? onPost(init)
      : String(url).includes("indexed-paths")
        ? Response.json([])
        : Response.json({}),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("GenerateEvalSetDialog", () => {
  it("does not render the trigger without eval.run", () => {
    renderDialog([PERMISSION.EVAL_READ]);
    expect(screen.queryByRole("button", { name: /generate eval set/i })).toBeNull();
  });

  it("submits the defaults: whole project, 25 questions, balanced", async () => {
    const fetchMock = pathsOrPost(() => Response.json({ id: "s1" }, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: /generate eval set/i }));
    fireEvent.change(await screen.findByLabelText(/^name/i), {
      target: { value: "Smoke" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^generate$/i }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
        true,
      ),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      name: "Smoke",
      sourcePath: null,
      count: 25,
      mix: "balanced",
    });
  });

  it("routes MODULE_PATH_NOT_INDEXED to the path field", async () => {
    vi.stubGlobal(
      "fetch",
      pathsOrPost(() =>
        Response.json(
          {
            detail: {
              code: "MODULE_PATH_NOT_INDEXED",
              message: "Nothing under that path is indexed.",
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: /generate eval set/i }));
    fireEvent.change(await screen.findByLabelText(/^name/i), {
      target: { value: "Smoke" },
    });
    fireEvent.change(screen.getByLabelText(/^path/i), { target: { value: "nope/" } });
    fireEvent.click(screen.getByRole("button", { name: /^generate$/i }));

    const message = await screen.findByText("Nothing under that path is indexed.");
    // Beside the path input, not in the form-level banner.
    expect(message).toHaveAttribute("data-slot", "field-error");
    expect(screen.getAllByText("Nothing under that path is indexed.")).toHaveLength(1);
    expect(screen.getByLabelText(/^path/i)).toHaveAttribute("aria-invalid", "true");
  });

  it("routes 422 sourcePath field error to the path field", async () => {
    vi.stubGlobal(
      "fetch",
      pathsOrPost(() =>
        Response.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message: "Validation error",
              fields: {
                sourcePath: "Path segment is invalid.",
              },
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: /generate eval set/i }));
    fireEvent.change(await screen.findByLabelText(/^name/i), {
      target: { value: "Test" },
    });
    fireEvent.change(screen.getByLabelText(/^path/i), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: /^generate$/i }));

    const message = await screen.findByText("Path segment is invalid.");
    // Beside the path input, not in the form-level banner.
    expect(message).toHaveAttribute("data-slot", "field-error");
    expect(screen.getAllByText("Path segment is invalid.")).toHaveLength(1);
    expect(screen.getByLabelText(/^path/i)).toHaveAttribute("aria-invalid", "true");
  });
});
