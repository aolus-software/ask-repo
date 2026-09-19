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
  4: "md:grid-cols-3 lg:grid-cols-4",
  5: "md:grid-cols-3 lg:grid-cols-5",
} as const;

/** Debounced so typing does not fire a request per keystroke. */
export function ListToolbar({
  initialSearch,
  placeholder,
  onSearchChange,
  filters,
  columns = 4,
}: {
  initialSearch: string;
  placeholder: string;
  onSearchChange: (value: string) => void;
  /**
   * Extra filter controls, dropped into the remaining grid cells. Pass them as
   * sibling cells (a fragment), never wrapped in a grid of their own -- a nested
   * grid lands in one cell and divides *that* cell between every control.
   */
  filters?: React.ReactNode;
  /** Total cells in the row, search included. Four unless the screen needs more. */
  columns?: keyof typeof COLUMN_LAYOUTS;
}) {
  const [value, setValue] = useState(initialSearch);

  useEffect(() => {
    if (value === initialSearch) return;
    const timer = setTimeout(() => onSearchChange(value), 300);
    return () => clearTimeout(timer);
  }, [value, initialSearch, onSearchChange]);

  return (
    <div className={cn("mb-4 grid grid-cols-1 gap-4", COLUMN_LAYOUTS[columns])}>
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
      {filters}
    </div>
  );
}
