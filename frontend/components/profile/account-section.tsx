"use client";

import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UserRoleBadge } from "@/components/users/user-role-badge";
import { useMemberships } from "@/hooks/use-profile";
import { useSession } from "@/hooks/use-session";

/** Who you are, and which projects you belong to — read-only (§4.0: admin-provisioned). */
export function AccountSection() {
  const user = useSession();
  const memberships = useMemberships();
  const rows = memberships.data ?? [];

  return (
    <Card className="gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <p className="text-foreground font-medium">{user.name}</p>
          <p className="text-muted-foreground text-sm">{user.email}</p>
        </div>
        <UserRoleBadge isAdmin={user.isAdmin} />
      </div>
      {user.isAdmin ? (
        <p className="text-muted-foreground text-sm">
          As an administrator you can see every project. The list below is only the ones
          you are a member of.
        </p>
      ) : null}

      {memberships.isError ? (
        <ListError error={memberships.error} onRetry={() => memberships.refetch()} />
      ) : !memberships.isLoading && rows.length === 0 ? (
        <EmptyState
          size="compact"
          description="You aren't a member of any project yet."
        />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Role</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {memberships.isLoading ? (
                <TableSkeleton columns={2} />
              ) : (
                rows.map((row) => (
                  <TableRow key={row.projectId}>
                    <TableCell>
                      <Link
                        href={`/projects/${row.projectId}`}
                        className="text-primary underline-offset-4 hover:underline"
                      >
                        {row.projectName}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm capitalize">{row.role}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}
