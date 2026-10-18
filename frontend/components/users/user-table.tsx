"use client";

import { useTranslations } from "next-intl";

import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { UserRoleBadge } from "@/components/users/user-role-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { UserResponse } from "@/lib/api/types";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

export function UserTable({
  users,
  isLoading,
  rowActions,
}: {
  users: UserResponse[];
  isLoading: boolean;
  rowActions: (user: UserResponse) => React.ReactNode;
}) {
  const t = useTranslations("settings.users.table");
  const formatRelative = useFormatRelative();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("columns.name")}</TableHead>
          <TableHead>{t("columns.email")}</TableHead>
          <TableHead>{t("columns.role")}</TableHead>
          <TableHead>{t("columns.lastLogin")}</TableHead>
          <TableHead>{t("columns.created")}</TableHead>
          <TableHead className="text-right">{t("columns.actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading ? (
          <TableSkeleton columns={6} />
        ) : (
          users.map((user) => (
            <TableRow key={user.id}>
              <TableCell className="font-medium">{user.name}</TableCell>
              <TableCell className="text-muted-foreground">{user.email}</TableCell>
              <TableCell>
                <UserRoleBadge isAdmin={user.isAdmin} />
              </TableCell>
              <TableCell title={formatAbsolute(user.lastLoginAt)}>
                {user.lastLoginAt ? formatRelative(user.lastLoginAt) : t("never")}
              </TableCell>
              <TableCell title={formatAbsolute(user.createdAt)}>
                {formatRelative(user.createdAt)}
              </TableCell>
              <TableCell className="text-right">{rowActions(user)}</TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
