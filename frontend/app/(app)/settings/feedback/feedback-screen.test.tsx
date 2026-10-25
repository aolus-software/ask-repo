import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FeedbackScreen } from "@/app/(app)/settings/feedback/feedback-screen";
import { ApiError } from "@/lib/api/errors";

const { searchState, replaceMock } = vi.hoisted(() => ({
  searchState: { value: "" },
  replaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  usePathname: () => "/settings/feedback",
  useSearchParams: () => new URLSearchParams(searchState.value),
}));

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    id: "u1",
    name: "Admin",
    email: "admin@example.com",
    isAdmin: true,
    mustChangePassword: false,
    lastLoginAt: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  }),
}));

const { useFeedbackListMock, useFeedbackSummaryMock } = vi.hoisted(() => ({
  useFeedbackListMock: vi.fn(),
  useFeedbackSummaryMock: vi.fn(),
}));

vi.mock("@/hooks/use-feedback", () => ({
  useFeedbackList: useFeedbackListMock,
  useFeedbackSummary: useFeedbackSummaryMock,
}));

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FeedbackScreen />
    </QueryClientProvider>,
  );
}

describe("FeedbackScreen", () => {
  it("shows a retryable error, not a blank section, when the summary fails to load", () => {
    useFeedbackListMock.mockReturnValue({
      data: { items: [], page: 1, limit: 25, totalCount: 0, totalPages: 1 },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    const refetchSummary = vi.fn();
    useFeedbackSummaryMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError(500, "INTERNAL_ERROR", "Could not load the summary."),
      refetch: refetchSummary,
    });

    renderScreen();

    expect(screen.getByText(/Something went wrong on our side/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetchSummary).toHaveBeenCalledTimes(1);
  });

  it("shows a skeleton, not nothing, while the summary is loading", () => {
    useFeedbackListMock.mockReturnValue({
      data: { items: [], page: 1, limit: 25, totalCount: 0, totalPages: 1 },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    useFeedbackSummaryMock.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    const { container } = renderScreen();

    expect(screen.queryByText("Could not load this list")).not.toBeInTheDocument();
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(
      0,
    );
  });

  describe("when the list is empty", () => {
    const emptyList = {
      data: { items: [], page: 1, limit: 25, totalCount: 0, totalPages: 1 },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
    const quietSummary = {
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };

    it("says there is no feedback yet when no filter is set", () => {
      searchState.value = "";
      useFeedbackListMock.mockReturnValue(emptyList);
      useFeedbackSummaryMock.mockReturnValue(quietSummary);
      renderScreen();

      expect(screen.getByText("No feedback yet")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
    });

    it("says nothing matches, with a clear action, when a filter is set", () => {
      searchState.value = "rating=down&createdFrom=2026-10-01";
      replaceMock.mockClear();
      useFeedbackListMock.mockReturnValue(emptyList);
      useFeedbackSummaryMock.mockReturnValue(quietSummary);
      renderScreen();

      expect(screen.getByText("No feedback matches these filters")).toBeInTheDocument();
      expect(screen.queryByText("No feedback yet")).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
      expect(replaceMock).toHaveBeenCalledWith("/settings/feedback", { scroll: false });
    });
  });
});
