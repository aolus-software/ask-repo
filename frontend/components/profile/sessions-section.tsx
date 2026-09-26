"use client";

import { useState } from "react";

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
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { deviceLabel } from "@/lib/user-agent";

/**
 * A hard load to `/login`, as the account menu does: it drops the React Query cache with
 * the session, so nothing of this operator survives into the next one on a shared machine.
 */
async function signOut(all: boolean) {
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ all }),
  });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- clears the in-memory cache with the session
  window.location.assign("/login");
}

export function SessionsSection() {
  const user = useSession();
  const sessions = useSessions();
  const revoke = useRevokeSession();
  const [pending, setPending] = useState<SessionSummary | null>(null);

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
      <p className="text-muted-foreground text-sm">
        Last signed in{" "}
        <span className="text-foreground" title={formatAbsolute(user.lastLoginAt)}>
          {user.lastLoginAt ? formatRelative(user.lastLoginAt) : "never"}
        </span>
      </p>

      {sessions.isError ? (
        <ListError error={sessions.error} onRetry={() => sessions.refetch()} />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead>IP address</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Last active</TableHead>
                <TableHead className="text-right">Actions</TableHead>
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
                          <StatusBadge tone="info" label="This device" />
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">{session.ipAddress ?? "—"}</TableCell>
                    <TableCell className="text-sm" title={formatAbsolute(session.startedAt)}>
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
                        Log out
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
          Log out everywhere
        </Button>
      </div>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title="Sign this session out?"
        description="It can't refresh again. It may stay signed in for up to 15 minutes, until its current access expires."
        confirmLabel="Sign it out"
        isPending={revoke.isPending}
        error={revoke.error}
        onConfirm={() =>
          pending && revoke.mutate(pending.id, { onSuccess: () => setPending(null) })
        }
      />
    </Card>
  );
}
