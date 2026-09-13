import { FileQuestion } from "lucide-react";

import { CenteredMessage } from "@/components/feedback/centered-message";

/** The 404 case — where the caller may not learn the resource exists at all. */
export function NotFound({ message }: { message?: string }) {
  return (
    <CenteredMessage
      icon={FileQuestion}
      level={2}
      title="Not found"
      description={message ?? "It may have been deleted, or it may never have existed."}
    />
  );
}
