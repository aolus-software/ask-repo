"use client";

import { UserPlus, Users } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { Forbidden } from "@/components/feedback/forbidden";
import { ListToolbar } from "@/components/layout/list-toolbar";
import { PageHeader } from "@/components/layout/page-header";
import { PaginationFooter } from "@/components/layout/pagination-footer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CreateUserDialog } from "@/components/users/create-user-dialog";
import { UserRowActions } from "@/components/users/user-row-actions";
import { UserTable } from "@/components/users/user-table";
import { useListParams } from "@/hooks/use-list-params";
import { useSession } from "@/hooks/use-session";
import { useUsers } from "@/hooks/use-users";
import { SORT } from "@/lib/api/endpoints";

export function UsersScreen() {
  const user = useSession();
  const [creating, setCreating] = useState(false);
  const { params, searchInput, setSearch, setPage } = useListParams({
    limit: 25,
    sort: SORT.users.createdAt,
    sortDirection: "desc",
  });
  const query = useUsers(params);

  const users = query.data?.items ?? [];

  // The route body is wrapped in its gate. Hiding the nav item is not gating the
  // route — an operator can type the URL (navigation.md §6). This mirrors the
  // backend's ADMIN_REQUIRED; it does not replace it.
  if (!user.isAdmin) return <Forbidden message="Only administrators can manage accounts." />;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Users"
        description="Accounts on this instance."
        action={
          <Button onClick={() => setCreating(true)}>
            <UserPlus className="size-4" />
            Add user
          </Button>
        }
      />

      <ListToolbar
        initialSearch={searchInput}
        placeholder="Search by name or email"
        onSearchChange={setSearch}
      />

      <Card className="p-0">
        {!query.isLoading && users.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No accounts match"
            description="Provision an account for a colleague to get them started."
            action={<Button onClick={() => setCreating(true)}>Add user</Button>}
          />
        ) : (
          <>
            <UserTable
              users={users}
              isLoading={query.isLoading}
              rowActions={(row) => <UserRowActions user={row} />}
            />
            <PaginationFooter
              page={query.data?.page ?? 1}
              totalPages={query.data?.totalPages ?? 1}
              totalCount={query.data?.totalCount ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>

      <CreateUserDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
