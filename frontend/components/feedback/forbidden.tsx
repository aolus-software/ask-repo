import { ShieldX } from "lucide-react";

/**
 * Rendered in place, never a redirect (`docs/design.md` → Feedback). Used where the
 * caller may see the resource but not act on it — the 403 case (response-api.md).
 */
export function Forbidden({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <ShieldX className="text-danger size-8" />
      <h2 className="text-xl font-semibold">You do not have access to this</h2>
      <p className="text-muted-foreground max-w-md text-base">
        {message ?? "Ask an administrator if you think you should."}
      </p>
    </div>
  );
}
