"use client";

import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { useDeleteEvalSet } from "@/hooks/use-eval";

/** Confirms deleting one eval set. Gated by the caller on `eval.run`, as the route is. */
export function DeleteEvalSetDialog({
  projectId,
  set,
  onOpenChange,
  onDeleted,
}: {
  projectId: string;
  /** The set being confirmed; `null` closes the dialog. */
  set: { id: string; name: string } | null;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}) {
  const remove = useDeleteEvalSet(projectId);

  return (
    <ConfirmDialog
      open={set !== null}
      onOpenChange={(open) => {
        if (!open) remove.reset();
        onOpenChange(open);
      }}
      title={set ? `Delete ${set.name}?` : "Delete eval set?"}
      description="Its questions, every run and all of their results are deleted with it, for everyone."
      confirmLabel="Delete eval set"
      isPending={remove.isPending}
      error={remove.error}
      onConfirm={() => {
        if (!set) return;
        remove.mutate(set.id, {
          onSuccess: () => {
            toast.success("Eval set deleted");
            onOpenChange(false);
            onDeleted?.();
          },
        });
      }}
    />
  );
}
