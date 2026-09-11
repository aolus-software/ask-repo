/**
 * Path arithmetic for the module path picker (phase 1.1).
 *
 * Split out of the component for the same reason `operations.ts` is: these are the
 * parts that can be wrong without looking wrong. A breadcrumb that drops a segment or
 * a parent that walks past the root are both silent in a render assertion.
 */

const SEPARATOR = "/";

/** Trim the slashes the backend also trims, so a typed path and a picked one match. */
export function normalisePath(path: string): string {
  return path.trim().replace(/^\/+/, "").replace(/\/+$/, "");
}

/**
 * The directory containing `path`, or `""` at the root.
 *
 * Never returns `path` itself: a "go up" that lands where it started is a dead button,
 * and the caller cannot tell the difference from the return value alone.
 */
export function parentOf(path: string): string {
  const normalised = normalisePath(path);
  const cut = normalised.lastIndexOf(SEPARATOR);
  return cut === -1 ? "" : normalised.slice(0, cut);
}

/**
 * The trail from the repository root down to `path`, root first.
 *
 * The root is always the first crumb and is labelled by the caller, because "the whole
 * repository" reads better than an empty string and this module does not do copy.
 */
export function breadcrumbTrail(path: string): { label: string; path: string }[] {
  const normalised = normalisePath(path);
  if (!normalised) return [];
  const segments = normalised.split(SEPARATOR);
  return segments.map((label, index) => ({
    label,
    path: segments.slice(0, index + 1).join(SEPARATOR),
  }));
}

/** What clicking one picker row does. `directory` is where the tree should sit after. */
export type PickerAction =
  | { kind: "select"; path: string; directory: string }
  | { kind: "open"; directory: string };

/**
 * Clicking a row means different things in the picker's two modes, and getting it
 * backwards is silent: a search result that navigates instead of selecting looks like
 * the click did nothing, because the row is still on screen.
 *
 * Browsing, a directory opens and a file is chosen. Searching, everything is chosen —
 * finding and picking is the entire purpose of the search box, and there is no tree
 * position to navigate within.
 */
export function actionFor(
  entry: { path: string; kind: "dir" | "file" },
  options: { searching: boolean },
): PickerAction {
  if (!options.searching && entry.kind === "dir") {
    return { kind: "open", directory: entry.path };
  }
  return {
    kind: "select",
    path: entry.path,
    // Land the tree where the choice was made, so a mis-click is corrected by looking
    // at its siblings rather than by browsing back from the root.
    directory: entry.kind === "dir" ? entry.path : parentOf(entry.path),
  };
}
