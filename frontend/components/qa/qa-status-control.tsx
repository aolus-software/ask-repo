"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDashed, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { QAPairDetailResponse, QAStatus, UserResponse } from "@/lib/api/types";
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { keys } from "@/lib/query/keys";
import { qaStatusLabel } from "@/lib/status";

const OPTIONS: { value: QAStatus; icon: typeof Check }[] = [
  { value: "unreviewed", icon: CircleDashed },
  { value: "pass", icon: Check },
  { value: "fail", icon: X },
];

/**
 * Setting the verdict is open to EVERY authenticated user, not just the pair's
 * creator or an admin — `docs/PRD.md:338`: "Any user may create and verify a pair."
 * This is deliberately the one control on the detail page that `canManageQAPair`
 * does not gate, and it renders outside the owner-only actions menu on purpose:
 * placing it there would read as gated when it is not. The backend enforces the
 * same shape (`PUT /qa-pairs/{id}/status` takes only `CurrentUser`), so do not
 * "fix" this into a 403 later — that would be a regression against the PRD.
 */
export function QAStatusControl({
  pairId,
  status,
  reviewedBy,
  reviewedAt,
}: {
  pairId: string;
  status: QAStatus;
  reviewedBy: string | null;
  reviewedAt: string | null;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (next: QAStatus) =>
      apiFetch<QAPairDetailResponse>(endpoints.qaPairs.status(pairId), {
        method: "PUT",
        body: JSON.stringify({ status: next }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
    },
    onError: () => {
      toast.error("Could not update the status. Try again.");
    },
  });

  // Reviewer's name for display only — reads the same GET /users/{id} route any
  // authenticated user may call, not an admin one.
  const reviewer = useQuery({
    queryKey: keys.users.detail(reviewedBy ?? ""),
    queryFn: () => apiFetch<UserResponse>(endpoints.users.detail(reviewedBy ?? "")),
    enabled: Boolean(reviewedBy),
  });

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Review</p>
      <div className="flex items-center gap-2">
        {OPTIONS.map((option) => {
          const Icon = option.icon;
          return (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={status === option.value ? "default" : "outline"}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate(option.value)}
            >
              <Icon className="size-4" />
              {qaStatusLabel(option.value)}
            </Button>
          );
        })}
      </div>
      {reviewedBy && reviewedAt ? (
        <p className="text-muted-foreground text-sm">
          Reviewed by {reviewer.data?.name ?? reviewedBy.slice(0, 8)} ·{" "}
          <span title={formatAbsolute(reviewedAt)}>{formatRelative(reviewedAt)}</span>
        </p>
      ) : null}
    </div>
  );
}
