import { Suspense } from "react";

import { NewConversationScreen } from "@/app/(app)/ask/new-conversation-screen";

/** Suspense is required: the screen reads useSearchParams for ?projectId. */
export default function AskPage() {
  return (
    <Suspense>
      <NewConversationScreen />
    </Suspense>
  );
}
