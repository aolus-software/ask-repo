"use client";

import { UserMinus, Users } from "lucide-react";
import { useTranslations } from "next-intl";
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
import { useRoleLabel } from "@/components/projects/use-role-label";
import { useChangeMemberRole, useRevokeMember } from "@/hooks/use-member-mutations";
import { useMembers } from "@/hooks/use-members";
import { useRoleOptions } from "@/hooks/use-role-options";
import { isApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/i18n/error-text";
import type { MemberResponse } from "@/lib/api/types";
import { can, PERMISSION } from "@/lib/can";
import { formatAbsolute } from "@/lib/dates";
import { useFormatRelative } from "@/hooks/use-format-date";

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
  const t = useTranslations("projects.memberTable");
  const errorText = useErrorText();
  const roleLabel = useRoleLabel();
  const mutation = useChangeMemberRole(projectId, member.userId);

  if (!editable) return <span>{roleLabel(member.role)}</span>;

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
              onSuccess: () => toast.success(t("roleChanged")),
              onError: (error) => {
                if (isApiError(error) && error.code === "LAST_OWNER") return;
                toast.error(errorText(error));
              },
            },
          );
        }}
        disabled={mutation.isPending}
      >
        <SelectTrigger
          className="w-36"
          aria-label={t("roleFor", { name: member.name })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {roleOptions.map((role) => (
            <SelectItem key={role.name} value={role.name}>
              {roleLabel(role.name)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isLastOwner ? (
        <p className="text-danger text-xs">{errorText(mutation.error)}</p>
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
  const t = useTranslations("projects.memberTable");
  const [confirming, setConfirming] = useState(false);
  const mutation = useRevokeMember(projectId, member.userId);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        aria-label={t("revokeLabel", { name: member.name })}
        onClick={() => setConfirming(true)}
      >
        <UserMinus className="size-4" />
      </Button>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("revokeDialog.title", { name: member.name })}
        description={t("revokeDialog.description")}
        confirmLabel={t("revokeDialog.confirm")}
        isPending={mutation.isPending}
        // 409 LAST_OWNER names no field, so it renders as this dialog's banner — the
        // dialog is already scoped to this one row's revoke action.
        error={mutation.error}
        onConfirm={() =>
          mutation.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("revokeDialog.revoked"));
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
  const t = useTranslations("projects.memberTable");
  const formatRelative = useFormatRelative();
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
  // (`docs/audit-finding-solved-logs.md` §U7.4).
  if (query.isError) {
    return <ListError error={query.error} onRetry={() => query.refetch()} />;
  }

  if (!query.isLoading && members.length === 0) {
    return (
      <EmptyState
        icon={Users}
        title={t("emptyTitle")}
        description={t("emptyDescription")}
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("columns.user")}</TableHead>
          <TableHead>{t("columns.role")}</TableHead>
          <TableHead>{t("columns.grantedBy")}</TableHead>
          <TableHead>{t("columns.grantedAt")}</TableHead>
          {canRevoke ? (
            <TableHead className="text-right">{t("columns.actions")}</TableHead>
          ) : null}
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
