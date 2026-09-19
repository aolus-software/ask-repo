"use client";

import { Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Forbidden } from "@/components/feedback/forbidden";
import { NotFound } from "@/components/feedback/not-found";
import { FormError } from "@/components/form/form-error";
import { FormPage } from "@/components/form/form-page";
import { PermissionMatrix } from "@/components/roles/permission-matrix";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { useUpdateRolePermissions } from "@/hooks/use-role-mutations";
import { usePermissionCatalog, useRole } from "@/hooks/use-roles";
import { isApiError } from "@/lib/api/errors";

/**
 * `FormPage` with `hideSubmit` for a system role: it has no submit row at all
 * (`.claude/rules/forms.md` §1 — rendering an editable-looking form that then
 * 403s on submit does the check backwards), which is what `hideSubmit` exists
 * to omit rather than merely disable.
 */
export function RoleMatrixScreen({ id }: { id: string }) {
  const router = useRouter();
  const roleQuery = useRole(id);
  const catalogQuery = usePermissionCatalog();
  const mutation = useUpdateRolePermissions(id);

  // Seeded during render, never from an effect (forms.md §6): keying on the role's id
  // means reopening a different role re-seeds, while the operator's own edits survive
  // a background refetch of the same one.
  const [seededId, setSeededId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  if (roleQuery.data && seededId !== roleQuery.data.id) {
    setSeededId(roleQuery.data.id);
    setSelected(new Set(roleQuery.data.permissions));
  }

  if (roleQuery.isLoading || catalogQuery.isLoading) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (roleQuery.isError) {
    if (isApiError(roleQuery.error) && roleQuery.error.status === 403) {
      return <Forbidden message={roleQuery.error.message} />;
    }
    return (
      <div className="mx-auto w-full max-w-3xl">
        <FormError error={roleQuery.error} />
      </div>
    );
  }

  if (catalogQuery.isError) {
    return (
      <div className="mx-auto w-full max-w-3xl">
        <FormError error={catalogQuery.error} />
      </div>
    );
  }

  if (roleQuery.notFound || !roleQuery.data) {
    return <NotFound message="That role does not exist, or it has been deleted." />;
  }

  const role = roleQuery.data;
  const groups = catalogQuery.data?.groups ?? [];

  function toggle(permission: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(permission)) next.delete(permission);
      else next.add(permission);
      return next;
    });
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate([...selected], {
      onSuccess: () => {
        toast.success("Permissions saved");
        router.push("/settings/roles");
      },
    });
  }

  if (role.isSystem) {
    return (
      <FormPage
        backHref="/settings/roles"
        title={role.name}
        description={role.description ?? "What this role can do on a project."}
        submitLabel=""
        isPending={false}
        error={null}
        onSubmit={() => {}}
        hideSubmit
      >
        <div className="space-y-6">
          <Alert>
            <Lock className="size-4" />
            <AlertDescription>
              viewer, editor and owner are built in and cannot be changed.
            </AlertDescription>
          </Alert>
          <PermissionMatrix
            groups={groups}
            selected={selected}
            onToggle={() => {}}
            disabled
          />
        </div>
      </FormPage>
    );
  }

  return (
    <FormPage
      backHref="/settings/roles"
      title={role.name}
      description={role.description ?? "What this role can do on a project."}
      submitLabel="Save permissions"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <PermissionMatrix groups={groups} selected={selected} onToggle={toggle} />
      <p className="text-muted-foreground mt-6 text-sm">
        Saving applies to everyone holding this role immediately — it takes effect on
        their very next request.
      </p>
    </FormPage>
  );
}
