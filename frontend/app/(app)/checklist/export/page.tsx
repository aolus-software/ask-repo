import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { ExportScreen } from "./export-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function ChecklistExportPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-3xl space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      }
    >
      <ExportScreen />
    </Suspense>
  );
}
