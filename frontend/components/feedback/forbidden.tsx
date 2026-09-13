import { ShieldX } from "lucide-react";

import { CenteredMessage } from "@/components/feedback/centered-message";

/**
 * Rendered in place, never a redirect (`docs/design.md` → Feedback). Used where the
 * caller may see the resource but not act on it — the 403 case (response-api.md).
 */
export function Forbidden({ message }: { message?: string }) {
  return (
    <CenteredMessage
      icon={ShieldX}
      tone="danger"
      level={2}
      title="You do not have access to this"
      description={message ?? "Ask an administrator if you think you should."}
    />
  );
}
