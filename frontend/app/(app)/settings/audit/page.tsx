import { Suspense } from "react";

import { AuditScreen } from "@/app/(app)/settings/audit/audit-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function AuditPage() {
  return (
    <Suspense>
      <AuditScreen />
    </Suspense>
  );
}
