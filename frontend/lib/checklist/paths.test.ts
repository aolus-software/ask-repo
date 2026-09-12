import { describe, expect, it } from "vitest";

import {
  actionFor,
  breadcrumbTrail,
  normalisePath,
  parentOf,
} from "@/lib/checklist/paths";

describe("normalisePath", () => {
  it("trims the slashes the backend also trims", () => {
    expect(normalisePath("  /backend/app/  ")).toBe("backend/app");
  });

  it("leaves the root as an empty string", () => {
    expect(normalisePath("/")).toBe("");
  });
});

describe("parentOf", () => {
  it("walks up one level", () => {
    expect(parentOf("backend/app/api")).toBe("backend/app");
  });

  it("stops at the root rather than returning the path it was given", () => {
    // A "go up" that lands where it started is a dead button, and the caller cannot
    // tell from the return value alone.
    expect(parentOf("backend")).toBe("");
    expect(parentOf("")).toBe("");
  });
});

describe("breadcrumbTrail", () => {
  it("accumulates each segment into a navigable path", () => {
    expect(breadcrumbTrail("backend/app/api")).toEqual([
      { label: "backend", path: "backend" },
      { label: "app", path: "backend/app" },
      { label: "api", path: "backend/app/api" },
    ]);
  });

  it("is empty at the root, where the caller supplies the label", () => {
    expect(breadcrumbTrail("")).toEqual([]);
  });
});

describe("actionFor", () => {
  it("opens a directory while browsing", () => {
    expect(
      actionFor({ path: "backend/app", kind: "dir" }, { searching: false }),
    ).toEqual({ kind: "open", directory: "backend/app" });
  });

  it("selects a directory while searching", () => {
    // Backwards, this looks like the click did nothing: the row is still on screen.
    expect(
      actionFor({ path: "backend/app", kind: "dir" }, { searching: true }),
    ).toEqual({ kind: "select", path: "backend/app", directory: "backend/app" });
  });

  it("selects a file in either mode and lands the tree beside it", () => {
    for (const searching of [true, false]) {
      expect(
        actionFor({ path: "backend/app/config.py", kind: "file" }, { searching }),
      ).toEqual({
        kind: "select",
        path: "backend/app/config.py",
        directory: "backend/app",
      });
    }
  });
});
