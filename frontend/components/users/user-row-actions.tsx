"use client";

import { KeyRound, MoreHorizontal, Pencil, UserMinus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EditUserDialog } from "@/components/users/edit-user-dialog";
import { ResetPasswordDialog } from "@/components/users/reset-password-dialog";
import { useDeactivateUser } from "@/hooks/use-user-mutations";
import type { UserResponse } from "@/lib/api/types";

export function UserRowActions({ user }: { user: UserResponse }) {
  const [editing, setEditing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const deactivate = useDeactivateUser(user.id);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${user.name}`}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => setEditing(true)}>
            <Pencil className="size-4" />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setResetting(true)}>
            <KeyRound className="size-4" />
            Reset password
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDeactivating(true)}>
            <UserMinus className="size-4" />
            Deactivate
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <EditUserDialog user={user} open={editing} onOpenChange={setEditing} />
      <ResetPasswordDialog user={user} open={resetting} onOpenChange={setResetting} />

      <ConfirmDialog
        open={deactivating}
        onOpenChange={setDeactivating}
        title={`Deactivate ${user.name}?`}
        description="Their sessions end immediately. Projects they created stay."
        confirmLabel="Deactivate"
        isPending={deactivate.isPending}
        // 409 LAST_ADMIN names no field, so it renders as this dialog's banner.
        error={deactivate.error}
        onConfirm={() =>
          deactivate.mutate(undefined, {
            onSuccess: () => {
              toast.success(`${user.name} deactivated`);
              setDeactivating(false);
            },
          })
        }
      />
    </>
  );
}
