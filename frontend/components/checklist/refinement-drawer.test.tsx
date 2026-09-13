import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MessagesSquare } from "lucide-react";
import { beforeEach, describe, expect, it } from "vitest";

import { RefinementDrawer } from "@/components/checklist/refinement-drawer";

/**
 * The drag itself is not covered here: jsdom implements neither
 * `setPointerCapture` nor layout, so a simulated drag would exercise a stub and
 * assert on a width no browser computed. The keyboard path runs the same clamp
 * and the same write, which is the part that fails silently.
 */
function renderDrawer(storageKey = "test-drawer") {
  return render(
    <RefinementDrawer
      label="Refine"
      icon={MessagesSquare}
      title="Refine this test plan"
      description="Ask for changes."
      storageKey={storageKey}
    >
      <p>panel</p>
    </RefinementDrawer>,
  );
}

async function openDrawer() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /refine/i }));
  return user;
}

function widthOf(handle: HTMLElement) {
  return Number(handle.getAttribute("aria-valuenow"));
}

describe("RefinementDrawer", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("opens at the default width when nothing is stored", async () => {
    renderDrawer();
    await openDrawer();

    expect(widthOf(screen.getByRole("separator", { name: /resize/i }))).toBe(768);
  });

  it("reopens at the width the operator last chose", async () => {
    /**
     * Phase 1 has no user-preference store, and component state resets on every
     * navigation — which would make a drag worth doing exactly once per page
     * view. `localStorage` is what makes the size stick.
     */
    window.localStorage.setItem("askrepo.drawer-width.test-drawer", "900");
    renderDrawer();
    await openDrawer();

    expect(widthOf(screen.getByRole("separator", { name: /resize/i }))).toBe(900);
  });

  it("keeps each drawer's width separate", async () => {
    window.localStorage.setItem("askrepo.drawer-width.other-drawer", "900");
    renderDrawer("test-drawer");
    await openDrawer();

    expect(widthOf(screen.getByRole("separator", { name: /resize/i }))).toBe(768);
  });

  it("resizes from the keyboard and persists the result", async () => {
    renderDrawer();
    const user = await openDrawer();
    const handle = screen.getByRole("separator", { name: /resize/i });

    handle.focus();
    await user.keyboard("{ArrowLeft}");

    // The drawer is anchored right, so ArrowLeft widens it.
    expect(widthOf(handle)).toBe(800);
    expect(window.localStorage.getItem("askrepo.drawer-width.test-drawer")).toBe("800");
  });

  it("will not shrink below the width the panels need", async () => {
    window.localStorage.setItem("askrepo.drawer-width.test-drawer", "380");
    renderDrawer();
    const user = await openDrawer();
    const handle = screen.getByRole("separator", { name: /resize/i });

    handle.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");

    expect(widthOf(handle)).toBe(360);
  });

  it("clamps a stored width that no longer fits the viewport", async () => {
    /**
     * A width dragged on a wide monitor, reopened on a narrow one. Without the
     * clamp the handle would report a number the drawer cannot honour, and the
     * first arrow key would resize from that phantom value.
     */
    window.localStorage.setItem("askrepo.drawer-width.test-drawer", "5000");
    renderDrawer();
    await openDrawer();

    expect(widthOf(screen.getByRole("separator", { name: /resize/i }))).toBe(
      window.innerWidth - 32,
    );
  });

  it("falls back to the default when the stored value is not a width", async () => {
    window.localStorage.setItem("askrepo.drawer-width.test-drawer", "wide please");
    renderDrawer();
    await openDrawer();

    expect(widthOf(screen.getByRole("separator", { name: /resize/i }))).toBe(768);
  });
});
