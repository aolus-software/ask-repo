import type { Metadata } from "next";
import { Suspense } from "react";

import { QAScreen } from "./qa-screen";

export const metadata: Metadata = { title: "QA List" };

/**
 * `QAScreen` reads `useSearchParams()` for its filter state, so this Server Component
 * wraps it in `Suspense` — omitting it fails `next build` on this route
 * (`.claude/rules/navigation.md` §6), the same reason `projects/page.tsx` does it.
 */
export default function QAPage() {
  return (
    <Suspense>
      <QAScreen />
    </Suspense>
  );
}
