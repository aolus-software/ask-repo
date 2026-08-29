import { Suspense } from "react";

import { ConversationRail } from "@/components/ask/conversation-rail";

/** Two panes. The rail is in the layout, so switching conversations does not remount it. */
export default function AskLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 md:flex-row">
      <Suspense>
        <ConversationRail />
      </Suspense>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
