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
      "/qa",
      "/settings",
    ]);
  });

  it("hides a group entirely when all of its children are unreachable", () => {
    expect(visibleNavTree(member).map((i) => i.href)).toEqual([
      "/",
      "/projects",
      "/ask",
      "/qa",
    ]);
  });

  it("resolves the settings children for an admin", () => {
    const settings = visibleNavTree(admin).find((i) => i.href === "/settings");
    expect(settings?.children?.map((c) => c.href)).toEqual(["/settings/users"]);
  });

  it("leaves `children` absent on a leaf rather than an empty array", () => {
    const projects = visibleNavTree(admin).find((i) => i.href === "/projects");
    expect(projects && "children" in projects).toBe(false);
  });

  it("shows the QA List to a non-admin", () => {
    const tree = visibleNavTree({ isAdmin: false });
    expect(tree.map((item) => item.href)).toContain("/qa");
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

  it("builds breadcrumbs for a QA pair", () => {
    const trail = resolveBreadcrumbs("/qa/abc-123", { isAdmin: false });
    expect(trail[0]).toEqual({ href: "/qa", label: "QA List" });
  });
});
