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

  it("hides Settings from a non-admin, whose group has no reachable child", () => {
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

    // Settings is now hidden entirely for non-admins, since all children are admin-only.
    expect(settings).toBeUndefined();
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
  it("names the profile page, which is reached from the account menu", () => {
    expect(resolveBreadcrumbs("/profile", member)).toEqual([
      { href: "/profile", label: "Profile" },
    ]);
  });

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
