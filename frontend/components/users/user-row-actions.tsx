"use client";

import { KeyRound, MoreHorizontal, Pencil, UserMinus } from "lucide-react";
import { useTranslations } from "next-intl";
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
import { LastOwnerNotice } from "@/components/users/last-owner-notice";
import { ResetPasswordDialog } from "@/components/users/reset-password-dialog";
import { useDeactivateUser } from "@/hooks/use-user-mutations";
import type { UserResponse } from "@/lib/api/types";

export function UserRowActions({ user }: { user: UserResponse }) {
  const t = useTranslations("settings.users");
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
              aria-label={t("actionsFor", { name: user.name })}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => setEditing(true)}>
            <Pencil className="size-4" />
            {t("actions.edit")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setResetting(true)}>
            <KeyRound className="size-4" />
            {t("actions.resetPassword")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDeactivating(true)}>
            <UserMinus className="size-4" />
            {t("actions.deactivate")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <EditUserDialog user={user} open={editing} onOpenChange={setEditing} />
      <ResetPasswordDialog user={user} open={resetting} onOpenChange={setResetting} />

      <ConfirmDialog
        open={deactivating}
        onOpenChange={setDeactivating}
        title={t("deactivate.title", { name: user.name })}
        description={t("deactivate.description")}
        confirmLabel={t("deactivate.confirm")}
        isPending={deactivate.isPending}
        // 409 LAST_ADMIN names no field, so it renders as this dialog's banner.
        error={deactivate.error}
        onConfirm={() =>
          deactivate.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("deactivate.done"));
              setDeactivating(false);
            },
          })
        }
      >
        <LastOwnerNotice error={deactivate.error} />
      </ConfirmDialog>
    </>
  );
}
