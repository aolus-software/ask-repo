"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Tailwind scans for literal class names, so the grid cannot be interpolated from a
 * number -- both layouts are written out and chosen by key.
 */
const COLUMN_LAYOUTS = {
  3: "md:grid-cols-3",
  4: "md:grid-cols-3 lg:grid-cols-4",
  5: "md:grid-cols-3 lg:grid-cols-5",
} as const;

/**
 * Debounced so typing does not fire a request per keystroke.
 *
 * `onSearchChange` is optional: a screen with nothing to search against (see
 * `NotificationsScreen`) omits it, and the search cell is not rendered at all rather
 * than being wired to a backend filter that quietly does nothing. Pass a `columns`
 * count that matches how many cells actually render.
 */
export function ListToolbar({
  initialSearch,
  placeholder,
  onSearchChange,
  filters,
  columns = 4,
}: {
  initialSearch?: string;
  placeholder?: string;
  onSearchChange?: (value: string) => void;
  /**
   * Extra filter controls, dropped into the remaining grid cells. Pass them as
   * sibling cells (a fragment), never wrapped in a grid of their own -- a nested
   * grid lands in one cell and divides *that* cell between every control.
   */
  filters?: React.ReactNode;
  /** Total cells in the row, search included when present. Four unless the screen
   * needs more, or three when there is no search cell. */
  columns?: keyof typeof COLUMN_LAYOUTS;
}) {
  const [value, setValue] = useState(initialSearch ?? "");

  useEffect(() => {
    if (!onSearchChange) return;
    if (value === initialSearch) return;
    const timer = setTimeout(() => onSearchChange(value), 300);
    return () => clearTimeout(timer);
  }, [value, initialSearch, onSearchChange]);

  return (
    <div className={cn("mb-4 grid grid-cols-1 gap-4", COLUMN_LAYOUTS[columns])}>
      {onSearchChange && (
        <div className="relative">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            className="pl-9"
            placeholder={placeholder}
            aria-label={placeholder}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
      )}
      {filters}
    </div>
  );
}
