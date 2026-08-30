import { FileQuestion } from "lucide-react";

/** The 404 case — where the caller may not learn the resource exists at all. */
export function NotFound({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center">
      <FileQuestion className="text-muted-foreground size-8" />
      <h2 className="text-xl font-semibold">Not found</h2>
      <p className="text-muted-foreground max-w-md text-base">
        {message ?? "It may have been deleted, or it may never have existed."}
      </p>
    </div>
  );
}
