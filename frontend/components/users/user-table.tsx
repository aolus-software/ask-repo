"use client";

import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { UserResponse } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";

export function UserTable({
  users,
  isLoading,
  rowActions,
}: {
  users: UserResponse[];
  isLoading: boolean;
  rowActions: (user: UserResponse) => React.ReactNode;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Email</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Last login</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Actions</TableHead>
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
                {user.isAdmin ? (
                  <Badge className="bg-primary text-primary-foreground">Admin</Badge>
                ) : (
                  <Badge variant="outline">Member</Badge>
                )}
              </TableCell>
              <TableCell title={formatAbsolute(user.lastLoginAt)}>
                {user.lastLoginAt ? formatRelative(user.lastLoginAt) : "Never"}
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
