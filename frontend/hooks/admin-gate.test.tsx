import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UsersScreen } from "@/app/(app)/settings/users/users-screen";
import { useAuditEvent, useAuditEvents } from "@/hooks/use-audit-events";
import { useFeedbackList, useFeedbackSummary } from "@/hooks/use-feedback";
import { usePermissionCatalog, useRole, useRoles } from "@/hooks/use-roles";
import { useUsers } from "@/hooks/use-users";

const { admin } = vi.hoisted(() => ({ admin: { value: false } }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/settings/users",
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    id: "u1",
    name: "Someone",
    email: "someone@example.com",
    isAdmin: admin.value,
    mustChangePassword: false,
    lastLoginAt: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  }),
}));

function setup() {
  const fetchMock = vi.fn(async () => Response.json({}));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { fetchMock, wrapper };
}

afterEach(() => {
  vi.unstubAllGlobals();
  admin.value = false;
});

describe("admin data hooks", () => {
  it("fetch nothing when `enabled` is false", async () => {
    const { fetchMock, wrapper } = setup();
    const off = { enabled: false };

    renderHook(
      () => {
        useUsers({}, off);
        useAuditEvents({}, off);
        useAuditEvent("e1", off);
        useRoles(off);
        useRole("r1", off);
        usePermissionCatalog(off);
        useFeedbackList({}, off);
        useFeedbackSummary({}, off);
      },
      { wrapper },
    );
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("still fetch by default", async () => {
    const { fetchMock, wrapper } = setup();

    renderHook(() => useUsers({}), { wrapper });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });
});

describe("an admin screen for a non-admin", () => {
  it("renders Forbidden and requests no data before the gate", async () => {
    const { fetchMock, wrapper } = setup();
    admin.value = false;

    render(<UsersScreen />, { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.getByText("You do not have access to this")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
