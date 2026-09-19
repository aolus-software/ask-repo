"use client";

import { UserMinus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListError } from "@/components/feedback/list-error";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useChangeMemberRole, useRevokeMember } from "@/hooks/use-member-mutations";
import { useMembers } from "@/hooks/use-members";
import { useRoleOptions } from "@/hooks/use-role-options";
import { isApiError } from "@/lib/api/errors";
import type { MemberResponse } from "@/lib/api/types";
import { can, PERMISSION } from "@/lib/can";
import { formatAbsolute, formatRelative } from "@/lib/dates";

/** The granter's name, resolved from the same member list — they hold a role here too
 * unless they have since been revoked, in which case there is nothing to resolve. */
function granterName(members: MemberResponse[], grantedBy: string | null): string {
  if (!grantedBy) return "—";
  return members.find((member) => member.userId === grantedBy)?.name ?? "—";
}

function RoleCell({
  projectId,
  member,
  editable,
  roleOptions,
}: {
  projectId: string;
  member: MemberResponse;
  editable: boolean;
  roleOptions: { name: string; label: string }[];
}) {
  const mutation = useChangeMemberRole(projectId, member.userId);

  if (!editable) return <span>{member.role}</span>;

  // 409 LAST_OWNER is about this row specifically — demoting the project's last
  // owner — so it renders here, under the control that caused it, not as a toast
  // that could be describing any row in the table.
  const isLastOwner =
    isApiError(mutation.error) && mutation.error.code === "LAST_OWNER";

  return (
    <div className="space-y-1">
      <Select
        value={member.role}
        onValueChange={(value: string | null | undefined) => {
          if (!value || value === member.role) return;
          mutation.mutate(
            { role: value },
            {
              onSuccess: () => toast.success("Role changed"),
              onError: (error) => {
                if (isApiError(error) && error.code === "LAST_OWNER") return;
                toast.error(
                  isApiError(error) ? error.message : "That did not update. Try again.",
                );
              },
            },
          );
        }}
        disabled={mutation.isPending}
      >
        <SelectTrigger className="w-36" aria-label={`Role for ${member.name}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {roleOptions.map((role) => (
            <SelectItem key={role.name} value={role.name}>
              {role.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isLastOwner ? (
        <p className="text-danger text-xs">{mutation.error?.message}</p>
      ) : null}
    </div>
  );
}

function RevokeAction({
  projectId,
  member,
}: {
  projectId: string;
  member: MemberResponse;
}) {
  const [confirming, setConfirming] = useState(false);
  const mutation = useRevokeMember(projectId, member.userId);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Revoke ${member.name}'s access`}
        onClick={() => setConfirming(true)}
      >
        <UserMinus className="size-4" />
      </Button>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Revoke ${member.name}'s access?`}
        description="They lose access to this project immediately."
        confirmLabel="Revoke access"
        isPending={mutation.isPending}
        // 409 LAST_OWNER names no field, so it renders as this dialog's banner — the
        // dialog is already scoped to this one row's revoke action.
        error={mutation.error}
        onConfirm={() =>
          mutation.mutate(undefined, {
            onSuccess: () => {
              toast.success("Access revoked");
              setConfirming(false);
            },
          })
        }
      />
    </>
  );
}

export function MemberTable({
  projectId,
  permissions,
}: {
  projectId: string;
  permissions: string[];
}) {
  const query = useMembers(projectId);
  const roleOptions = useRoleOptions();
  const canGrant = can({ permissions }, PERMISSION.MEMBERSHIP_GRANT);
  const canRevoke = can({ permissions }, PERMISSION.MEMBERSHIP_REVOKE);
  const members = query.data ?? [];
  const columns = canRevoke ? 5 : 4;

  // A failed request and an empty result are different facts, and this table is where
  // collapsing them is worst: every project keeps at least one owner, so "no rows" can
  // only mean the request failed -- yet it reads as "access was revoked from everyone"
  // to the person who opened this tab to check exactly that
  // (`docs/ui-audit-findings.md` §U7.4).
  if (query.isError) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  if (!query.isLoading && members.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title="No members"
        description="Nobody holds a membership on this project yet."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>User</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Granted by</TableHead>
          <TableHead>Granted at</TableHead>
          {canRevoke ? <TableHead className="text-right">Actions</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {query.isLoading ? (
          <TableSkeleton columns={columns} />
        ) : (
          members.map((member) => (
            <TableRow key={member.userId}>
              <TableCell>
                <div className="font-medium">{member.name}</div>
                <div className="text-muted-foreground text-sm">{member.email}</div>
              </TableCell>
              <TableCell>
                <RoleCell
                  projectId={projectId}
                  member={member}
                  editable={canGrant}
                  roleOptions={roleOptions}
                />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {granterName(members, member.grantedBy)}
              </TableCell>
              <TableCell title={formatAbsolute(member.grantedAt)}>
                {formatRelative(member.grantedAt)}
              </TableCell>
              {canRevoke ? (
                <TableCell className="text-right">
                  <RevokeAction projectId={projectId} member={member} />
                </TableCell>
              ) : null}
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
