import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FeedbackScreen } from "@/app/(app)/settings/feedback/feedback-screen";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/settings/feedback",
  useSearchParams: () => new URLSearchParams(),
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

    expect(screen.getByText("Could not load the summary.")).toBeInTheDocument();

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
});
