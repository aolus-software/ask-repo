import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { ChecklistScreen } from "./checklist-screen";

/**
 * A Server Component wrapping the client screen in `<Suspense>`. Load-bearing: the
 * screen reads `useSearchParams()`, and without the boundary `next build` fails on
 * this route (`.claude/rules/navigation.md`).
 */
export default function ChecklistPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto w-full max-w-7xl space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      }
    >
      <ChecklistScreen />
    </Suspense>
  );
}
