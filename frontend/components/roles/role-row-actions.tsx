"use client";

import { Eye, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
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
import { useDeleteRole } from "@/hooks/use-role-mutations";
import type { RoleResponse } from "@/lib/api/types";

/**
 * A system role (viewer/editor/owner) offers only View — no Edit, no Delete. A menu
 * item that opens a dialog which then refuses is worse than an absent one. A custom
 * role's "Edit" is the same destination as "View": the matrix page itself decides
 * whether the grid is editable.
 */
export function RoleRowActions({ role }: { role: RoleResponse }) {
  const t = useTranslations("roles");
  const [deleting, setDeleting] = useState(false);
  const remove = useDeleteRole(role.id);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("actionsFor", { name: role.name })}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {role.isSystem ? (
            <DropdownMenuItem render={<Link href={`/settings/roles/${role.id}`} />}>
              <Eye className="size-4" />
              {t("actions.view")}
            </DropdownMenuItem>
          ) : (
            <>
              <DropdownMenuItem render={<Link href={`/settings/roles/${role.id}`} />}>
                <Pencil className="size-4" />
                {t("actions.edit")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setDeleting(true)}>
                <Trash2 className="size-4" />
                {t("actions.delete")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {role.isSystem ? null : (
        <ConfirmDialog
          open={deleting}
          onOpenChange={setDeleting}
          title={t("delete.title", { name: role.name })}
          description={t("delete.description")}
          confirmLabel={t("delete.confirm")}
          isPending={remove.isPending}
          // 409 ROLE_IN_USE names no field, so it renders as this dialog's banner.
          error={remove.error}
          onConfirm={() =>
            remove.mutate(undefined, {
              onSuccess: () => {
                toast.success(t("delete.done"));
                setDeleting(false);
              },
            })
          }
        />
      )}
    </>
  );
}
