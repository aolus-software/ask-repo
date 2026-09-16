"use client";

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
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Description</TableHead>
          <TableHead>Permissions</TableHead>
          <TableHead>Members</TableHead>
          <TableHead className="text-right">Actions</TableHead>
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
                {role.description ?? "—"}
              </TableCell>
              <TableCell>
                {role.permissions.length} of {totalPermissions}
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
