import { describe, expect, it } from "vitest";

import { resolveBreadcrumbs, visibleNavTree } from "@/lib/nav";

const admin = { isAdmin: true };
const member = { isAdmin: false };

describe("visibleNavTree", () => {
  it("shows the five destinations that exist to an admin", () => {
    expect(visibleNavTree(admin).map((i) => i.href)).toEqual([
      "/",
      "/projects",
      "/ask",
      "/checklist",
      "/settings",
    ]);
  });

  it("hides a group entirely when all of its children are unreachable", () => {
    expect(visibleNavTree(member).map((i) => i.href)).toEqual([
      "/",
      "/projects",
      "/ask",
      "/checklist",
    ]);
  });

  it("resolves the settings children for an admin", () => {
    const settings = visibleNavTree(admin).find((i) => i.href === "/settings");
    expect(settings?.children?.map((c) => c.href)).toEqual([
      "/settings/users",
      "/settings/roles",
      "/settings/audit",
    ]);
  });

  it("hides Roles from a non-admin", () => {
    const settings = visibleNavTree(member).find((i) => i.href === "/settings");
    expect(settings?.children?.map((c) => c.title) ?? []).not.toContain("Roles");
  });

  it("shows Roles to an admin", () => {
    const settings = visibleNavTree(admin).find((i) => i.href === "/settings");
    expect(settings?.children?.map((c) => c.title)).toContain("Roles");
  });

  it("leaves `children` absent on a leaf rather than an empty array", () => {
    const projects = visibleNavTree(admin).find((i) => i.href === "/projects");
    expect(projects && "children" in projects).toBe(false);
  });

  it("points at the checklist rather than the retired QA List", () => {
    const tree = visibleNavTree({ isAdmin: false });
    const hrefs = tree.map((item) => item.href);

    expect(hrefs).toContain("/checklist");
    expect(hrefs).not.toContain("/qa");
  });

  it("hides the audit trail from a non-admin", () => {
    const settings = visibleNavTree({ isAdmin: false }).find(
      (item) => item.title === "Settings",
    );

    // `settings` is `undefined` here, not a group with no matching child: every
    // child of Settings is `adminOnly`, so a non-admin's tree hides the group
    // entirely (`visibleNavTree` drops a group whose children all filter out).
    // `?? false` makes that the same assertion either way, matching the `?? []`
    // pattern the existing "hides Roles" test above already uses for this reason.
    expect(
      settings?.children?.some((child) => child.href === "/settings/audit") ?? false,
    ).toBe(false);
  });

  it("shows the audit trail to an admin", () => {
    const settings = visibleNavTree({ isAdmin: true }).find(
      (item) => item.title === "Settings",
    );

    expect(settings?.children?.some((child) => child.href === "/settings/audit")).toBe(
      true,
    );
  });
});

describe("resolveBreadcrumbs", () => {
  it("resolves a trail by longest matching nav item", () => {
    expect(resolveBreadcrumbs("/settings/users", admin)).toEqual([
      { href: "/settings", label: "Settings" },
      { href: "/settings/users", label: "Users" },
    ]);
  });

  it("returns a single crumb for a top-level destination", () => {
    expect(resolveBreadcrumbs("/projects", member)).toEqual([
      { href: "/projects", label: "Projects" },
    ]);
  });

  it("appends a detail crumb for an id segment", () => {
    const trail = resolveBreadcrumbs("/projects/abc-123", member);
    expect(trail[0]).toEqual({ href: "/projects", label: "Projects" });
    expect(trail).toHaveLength(2);
  });

  it("is empty on the dashboard", () => {
    expect(resolveBreadcrumbs("/", member)).toEqual([]);
  });

  it("resolves a breadcrumb trail into a module", () => {
    expect(resolveBreadcrumbs("/checklist/abc-123", { isAdmin: false })).toEqual([
      { href: "/checklist", label: "Checklist" },
      { href: "/checklist/abc-123", label: "abc-123" },
    ]);
  });
});
