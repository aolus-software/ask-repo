import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FeedbackControl } from "@/components/output-feedback/feedback-control";
import * as client from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

function renderControl(props: Partial<React.ComponentProps<typeof FeedbackControl>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <FeedbackControl targetType="message" targetId="m1" initial={null} {...props} />
    </QueryClientProvider>,
  );
}

describe("FeedbackControl", () => {
  it("records a thumbs-up in one click", async () => {
    const fetch = vi.spyOn(client, "apiFetch").mockResolvedValue({});
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));

    expect(fetch).toHaveBeenCalledWith(
      "/feedback/message/m1",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({
      rating: "up",
      reasonCodes: [],
      note: null,
    });
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("asks why on a thumbs-down, with the disclosure, and needs a reason", async () => {
    const fetch = vi.spyOn(client, "apiFetch").mockResolvedValue({});
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: /not helpful/i }));

    expect(
      screen.getByText("Administrators can read this note. It is never sent to the AI model."),
    ).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: /send feedback/i });
    expect(submit).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /cited the wrong file/i }));
    await userEvent.type(screen.getByRole("textbox"), "Pointed at the old router.");
    await userEvent.click(submit);

    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({
      rating: "down",
      reasonCodes: ["wrong_file_cited"],
      note: "Pointed at the old router.",
    });
  });

  it("offers change-set reasons on a change set", async () => {
    renderControl({ targetType: "checklist_change_set" });

    await userEvent.click(screen.getByRole("button", { name: /not helpful/i }));

    expect(screen.getByRole("checkbox", { name: /wrong scope/i })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /cited the wrong file/i })).toBeNull();
  });

  it("withdraws when the active thumb is clicked again", async () => {
    const fetch = vi.spyOn(client, "apiFetch").mockResolvedValue(undefined);
    renderControl({ initial: { rating: "up", reasonCodes: [], note: null } });

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));

    expect(fetch).toHaveBeenCalledWith(
      "/feedback/message/m1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("rolls back when the vote fails", async () => {
    vi.spyOn(client, "apiFetch").mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "Boom"),
    );
    renderControl();

    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute(
        "aria-pressed",
        "false",
      ),
    );
  });
});
