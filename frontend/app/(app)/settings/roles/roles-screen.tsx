"use client";

import { Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { Forbidden } from "@/components/feedback/forbidden";
import { ListError } from "@/components/feedback/list-error";
import { PageHeader } from "@/components/layout/page-header";
import { CreateRoleDialog } from "@/components/roles/create-role-dialog";
import { RoleRowActions } from "@/components/roles/role-row-actions";
import { RoleTable } from "@/components/roles/role-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { usePermissionCatalog, useRoles } from "@/hooks/use-roles";

export function RolesScreen() {
  const user = useSession();
  const [creating, setCreating] = useState(false);
  const rolesQuery = useRoles();
  const catalogQuery = usePermissionCatalog();

  const roles = rolesQuery.data ?? [];
  const totalPermissions =
    catalogQuery.data?.groups.reduce(
      (sum, group) => sum + group.permissions.length,
      0,
    ) ?? 0;
  const isLoading = rolesQuery.isLoading || catalogQuery.isLoading;

  // The route body is wrapped in its gate. Hiding the nav item is not gating the
  // route — an operator can type the URL (navigation.md §6). This mirrors the
  // backend's `require_admin`; it does not replace it.
  if (!user.isAdmin)
    return <Forbidden message="Only administrators can manage roles." />;

  return (
    <div className="mx-auto w-full max-w-7xl">
      <PageHeader
        title="Roles"
        description="Instance-wide role definitions and what each one can do."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" />
            Create role
          </Button>
        }
      />

      <Card className="p-0">
        {rolesQuery.isError ? (
          <div className="p-6">
            <ListError error={rolesQuery.error} onRetry={() => rolesQuery.refetch()} />
          </div>
        ) : !isLoading && roles.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No roles yet"
            description="Create a role to grant something other than viewer, editor or owner."
            action={<Button onClick={() => setCreating(true)}>Create role</Button>}
          />
        ) : (
          <RoleTable
            roles={roles}
            totalPermissions={totalPermissions}
            isLoading={isLoading}
            rowActions={(row) => <RoleRowActions role={row} />}
          />
        )}
      </Card>

      <CreateRoleDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
