"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";

/** Debounced so typing does not fire a request per keystroke. */
export function ListToolbar({
  initialSearch,
  placeholder,
  onSearchChange,
  filters,
}: {
  initialSearch: string;
  placeholder: string;
  onSearchChange: (value: string) => void;
  /** Extra filter controls, dropped into the remaining grid cells. */
  filters?: React.ReactNode;
}) {
  const [value, setValue] = useState(initialSearch);

  useEffect(() => {
    if (value === initialSearch) return;
    const timer = setTimeout(() => onSearchChange(value), 300);
    return () => clearTimeout(timer);
  }, [value, initialSearch, onSearchChange]);

  return (
    <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-4">
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
