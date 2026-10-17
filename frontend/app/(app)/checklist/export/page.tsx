import { Suspense } from "react";

import { ExportScreen } from "./export-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function ChecklistExportPage() {
  return (
    <Suspense fallback={null}>
      <ExportScreen />
    </Suspense>
  );
}
