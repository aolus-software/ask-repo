"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

type Labels = Record<string, string>;

interface BreadcrumbLabelsValue {
  labels: Labels;
  set: (href: string, label: string | null) => void;
}

/** Without a provider (a screen under test) naming a crumb is a quiet no-op. */
const BreadcrumbLabelsContext = createContext<BreadcrumbLabelsValue>({
  labels: {},
  set: () => {},
});

/**
 * Holds the display names detail pages have given their crumbs, keyed by the crumb's
 * `href`. `AppBreadcrumbs` hands them to `resolveBreadcrumbs`, which prefers a name
 * over the raw id segment; `lib/nav.ts` stays the one source of labels and hrefs
 * (`.claude/rules/navigation.md` §1), this only supplies the name an id cannot.
 */
export function BreadcrumbLabelsProvider({ children }: { children: React.ReactNode }) {
  const [labels, setLabels] = useState<Labels>({});
  // Stable, so a page's effect depending on it does not re-run (and re-register its
  // name, which re-renders this provider) on every change to `labels`.
  const set = useCallback((href: string, label: string | null) => {
    setLabels((current) => {
      if (label === null) {
        if (!(href in current)) return current;
        const rest = { ...current };
        delete rest[href];
        return rest;
      }
      return current[href] === label ? current : { ...current, [href]: label };
    });
  }, []);
  const value = useMemo<BreadcrumbLabelsValue>(() => ({ labels, set }), [labels, set]);

  return (
    <BreadcrumbLabelsContext.Provider value={value}>
      {children}
    </BreadcrumbLabelsContext.Provider>
  );
}

/** The names registered so far, for `AppBreadcrumbs`. */
export function useBreadcrumbLabels(): Labels {
  return useContext(BreadcrumbLabelsContext).labels;
}

/**
 * A detail page names its own crumb once it knows the resource:
 *
 *     useBreadcrumbLabel(`/projects/${id}`, project.data?.name);
 *
 * `href` is the crumb's href exactly as `resolveBreadcrumbs` builds it (the page's
 * own pathname for the last crumb, or an ancestor's, such as `/projects/${id}` from
 * an eval set page). A `label` of `undefined` -- still loading, or failed -- leaves
 * the raw segment showing. The name is removed again when the page unmounts.
 */
export function useBreadcrumbLabel(href: string, label: string | null | undefined) {
  const { set } = useContext(BreadcrumbLabelsContext);

  useEffect(() => {
    if (!label) return;
    set(href, label);
    return () => set(href, null);
  }, [href, label, set]);
}
