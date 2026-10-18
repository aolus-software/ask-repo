"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { ListError } from "@/components/feedback/list-error";
import { StatusBadge } from "@/components/feedback/status-badge";
import { TableSkeleton } from "@/components/feedback/table-skeleton";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRevokeSession, useSessions } from "@/hooks/use-profile";
import { useSession } from "@/hooks/use-session";
import type { SessionSummary } from "@/lib/api/types";
import { signOut } from "@/lib/auth/sign-out";
import { formatAbsolute } from "@/lib/dates";
import { deviceLabel } from "@/lib/user-agent";
import { useFormatRelative } from "@/hooks/use-format-date";

export function SessionsSection() {
  const t = useTranslations("profile.sessions");
  const formatRelative = useFormatRelative();
  const user = useSession();
  const sessions = useSessions();
  const revoke = useRevokeSession();
  const [pending, setPending] = useState<SessionSummary | null>(null);

  const lastSignedIn = t.rich("lastSignedIn", {
    time: user.lastLoginAt ? formatRelative(user.lastLoginAt) : t("never"),
    when: (chunks) => (
      <span className="text-foreground" title={formatAbsolute(user.lastLoginAt)}>
        {chunks}
      </span>
    ),
  });

  function logOut(session: SessionSummary) {
    if (session.current) {
      // Revoking this device's family and signing out are the same act; the logout
      // route also clears the cookies Next holds.
      void signOut(false);
      return;
    }
    setPending(session);
  }

  return (
    <Card className="gap-4 p-6">
      <p className="text-muted-foreground text-sm">{lastSignedIn}</p>

      {sessions.isError ? (
        <ListError error={sessions.error} onRetry={() => sessions.refetch()} />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("columns.device")}</TableHead>
                <TableHead>{t("columns.ipAddress")}</TableHead>
                <TableHead>{t("columns.started")}</TableHead>
                <TableHead>{t("columns.lastActive")}</TableHead>
                <TableHead className="text-right">{t("columns.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessions.isLoading ? (
                <TableSkeleton columns={5} />
              ) : (
                (sessions.data ?? []).map((session) => (
                  <TableRow key={session.id}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        <span title={session.userAgent ?? undefined}>
                          {deviceLabel(session.userAgent)}
                        </span>
                        {session.current ? (
                          <StatusBadge tone="info" label={t("thisDevice")} />
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {session.ipAddress ?? "—"}
                    </TableCell>
                    <TableCell
                      className="text-sm"
                      title={formatAbsolute(session.startedAt)}
                    >
                      {formatRelative(session.startedAt)}
                    </TableCell>
                    <TableCell
                      className="text-sm"
                      title={formatAbsolute(session.lastActiveAt)}
                    >
                      {formatRelative(session.lastActiveAt)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => logOut(session)}>
                        {t("logOut")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="outline" onClick={() => void signOut(true)}>
          {t("logOutEverywhere")}
        </Button>
      </div>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={t("confirmTitle")}
        description={t("confirmDescription")}
        confirmLabel={t("confirmLabel")}
        isPending={revoke.isPending}
        error={revoke.error}
        onConfirm={() =>
          pending &&
          revoke.mutate(pending.id, {
            onSuccess: () => {
              toast.success(t("signedOut"));
              setPending(null);
            },
          })
        }
      />
    </Card>
  );
}
