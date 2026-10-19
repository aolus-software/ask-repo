"use client";

import { useTranslations } from "next-intl";

import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { RoleBadge } from "@/components/roles/role-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { RoleResponse } from "@/lib/api/types";

export function RoleTable({
  roles,
  totalPermissions,
  isLoading,
  rowActions,
}: {
  roles: RoleResponse[];
  /** The full permission catalogue size, so "n of total" means something. */
  totalPermissions: number;
  isLoading: boolean;
  rowActions: (role: RoleResponse) => React.ReactNode;
}) {
  const t = useTranslations("roles.table");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("columns.name")}</TableHead>
          <TableHead>{t("columns.description")}</TableHead>
          <TableHead>{t("columns.permissions")}</TableHead>
          <TableHead>{t("columns.members")}</TableHead>
          <TableHead className="text-right">{t("columns.actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading ? (
          <TableSkeleton columns={5} />
        ) : (
          roles.map((role) => (
            <TableRow key={role.id}>
              <TableCell className="font-medium">
                <RoleBadge name={role.name} isSystem={role.isSystem} />
              </TableCell>
              <TableCell className="text-muted-foreground max-w-xs truncate">
                {role.description ?? t("noDescription")}
              </TableCell>
              <TableCell>
                {t("permissionCount", {
                  count: role.permissions.length,
                  total: totalPermissions,
                })}
              </TableCell>
              <TableCell>{role.memberCount}</TableCell>
              <TableCell className="text-right">{rowActions(role)}</TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
