import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileScreen } from "@/components/profile/profile-screen";

// The sections fetch their own data; this suite is about which one is showing.
vi.mock("@/components/profile/account-section", () => ({
  AccountSection: () => <p>account body</p>,
}));
vi.mock("@/components/profile/sessions-section", () => ({
  SessionsSection: () => <p>sessions body</p>,
}));
vi.mock("@/components/profile/activity-section", () => ({
  ActivitySection: () => <p>activity body</p>,
}));
vi.mock("@/components/profile/password-section", () => ({
  PasswordSection: () => <p>password body</p>,
}));
vi.mock("@/components/notifications/preferences-screen", () => ({
  PreferencesScreen: () => <p>notifications body</p>,
}));

afterEach(() => window.history.replaceState(null, "", "/"));

describe("ProfileScreen", () => {
  it("opens on Account", () => {
    render(<ProfileScreen resetEnabled={false} />);
    expect(screen.getByRole("tab", { name: "Account" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("account body")).toBeInTheDocument();
  });

  it("opens the tab the hash names — where /settings/notifications redirects", () => {
    window.history.replaceState(null, "", "/profile#notifications");
    render(<ProfileScreen resetEnabled={false} />);
    expect(screen.getByRole("tab", { name: "Notifications" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("notifications body")).toBeInTheDocument();
  });

  it("switches section and writes it to the hash", () => {
    render(<ProfileScreen resetEnabled={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "Sessions" }));
    expect(screen.getByText("sessions body")).toBeInTheDocument();
    expect(window.location.hash).toBe("#sessions");
  });
});
