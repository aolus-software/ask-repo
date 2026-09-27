import { Suspense } from "react";

import { FeedbackScreen } from "@/app/(app)/settings/feedback/feedback-screen";

/** Suspense is required: the screen reads useSearchParams (navigation.md §6). */
export default function FeedbackPage() {
  return (
    <Suspense>
      <FeedbackScreen />
    </Suspense>
  );
}
