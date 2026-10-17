import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  BreadcrumbLabelsProvider,
  useBreadcrumbLabel,
  useBreadcrumbLabels,
} from "@/components/layout/breadcrumb-labels";
import { resolveBreadcrumbs } from "@/lib/nav";

const admin = { isAdmin: true };

function Trail({ pathname }: { pathname: string }) {
  const labels = useBreadcrumbLabels();
  return (
    <p data-testid="trail">
      {resolveBreadcrumbs(pathname, admin, labels)
        .map((crumb) => crumb.label)
        .join(" / ")}
    </p>
  );
}

function Page({ label }: { label: string | undefined }) {
  useBreadcrumbLabel("/projects/abc", label);
  return null;
}

describe("resolveBreadcrumbs with labels", () => {
  it("prefers a registered name over the raw id segment", () => {
    const trail = resolveBreadcrumbs("/projects/abc", admin, {
      "/projects/abc": "Payments API",
    });
    expect(trail.map((c) => c.label)).toEqual(["Projects", "Payments API"]);
  });

  it("names the project and the set on an eval set path", () => {
    const trail = resolveBreadcrumbs("/projects/p1/eval/s1", admin, {
      "/projects/p1": "Payments API",
      "/projects/p1/eval/s1": "Baseline",
    });
    expect(trail.map((c) => c.label)).toEqual([
      "Projects",
      "Payments API",
      "Eval",
      "Baseline",
    ]);
  });

  it("never renames a nav item, only id-derived crumbs", () => {
    const trail = resolveBreadcrumbs("/projects", admin, { "/projects": "Hijacked" });
    expect(trail.map((c) => c.label)).toEqual(["Projects"]);
  });

  it("keeps the raw segment when no name is known", () => {
    expect(resolveBreadcrumbs("/projects/abc", admin).at(-1)?.label).toBe("abc");
  });
});

describe("useBreadcrumbLabel", () => {
  it("shows the name once known and the raw id until then", () => {
    const { rerender } = render(
      <BreadcrumbLabelsProvider>
        <Trail pathname="/projects/abc" />
        <Page label={undefined} />
      </BreadcrumbLabelsProvider>,
    );
    expect(screen.getByTestId("trail").textContent).toBe("Projects / abc");

    act(() => {
      rerender(
        <BreadcrumbLabelsProvider>
          <Trail pathname="/projects/abc" />
          <Page label="Payments API" />
        </BreadcrumbLabelsProvider>,
      );
    });
    expect(screen.getByTestId("trail").textContent).toBe("Projects / Payments API");
  });

  it("drops the name when the page unmounts", () => {
    const { rerender } = render(
      <BreadcrumbLabelsProvider>
        <Trail pathname="/projects/abc" />
        <Page label="Payments API" />
      </BreadcrumbLabelsProvider>,
    );
    rerender(
      <BreadcrumbLabelsProvider>
        <Trail pathname="/projects/abc" />
      </BreadcrumbLabelsProvider>,
    );
    expect(screen.getByTestId("trail").textContent).toBe("Projects / abc");
  });

  it("is a no-op without a provider", () => {
    expect(() => render(<Page label="Payments API" />)).not.toThrow();
  });
});
