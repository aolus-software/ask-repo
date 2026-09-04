import { Suspense } from "react";

import { ChecklistScreen } from "./checklist-screen";

/**
 * A Server Component wrapping the client screen in `<Suspense>`. Load-bearing: the
 * screen reads `useSearchParams()`, and without the boundary `next build` fails on
 * this route (`.claude/rules/navigation.md`).
 */
export default function ChecklistPage() {
  return (
    <Suspense fallback={null}>
      <ChecklistScreen />
    </Suspense>
  );
}
