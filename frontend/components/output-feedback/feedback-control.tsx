"use client";

import { useMutation } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  NOTE_DISCLOSURE,
  NOTE_MAX_LENGTH,
  REASON_LABELS,
  reasonsFor,
} from "@/components/output-feedback/reason-labels";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  FeedbackRating,
  FeedbackReasonCode,
  FeedbackTargetType,
  MyFeedback,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface FeedbackControlProps {
  targetType: FeedbackTargetType;
  targetId: string;
  initial: MyFeedback | null | undefined;
  className?: string;
}

/**
 * Thumbs up/down on one model-authored output, and on a thumbs-down, why.
 *
 * The vote is the caller's own and nobody else sees it on this screen
 * (`.claude/rules/feedback.md`). Optimistic, with a local rollback: the list
 * that supplied `initial` is not refetched, because nothing else on the
 * screen depends on the vote.
 *
 * `initial` can change under us — a cached list refetches while this control
 * is mounted, or the same control remounts against a fresh `initial` from
 * cache within the query's `gcTime`. Re-seeding is done during render, the
 * same pattern `forms.md` rule 6 uses for an edit form: state tracks the
 * `initial` it was last seeded from and re-seeds when that no longer
 * matches, rather than in an effect, which would cost an extra render pass.
 * It is skipped while a mutation is in flight so an in-progress vote is
 * never clobbered by a stale `initial` racing it.
 */
export function FeedbackControl({
  targetType,
  targetId,
  initial,
  className,
}: FeedbackControlProps) {
  const [vote, setVote] = useState<MyFeedback | null>(initial ?? null);
  const [open, setOpen] = useState(false);
  const [reasons, setReasons] = useState<FeedbackReasonCode[]>(
    initial?.reasonCodes ?? [],
  );
  const [note, setNote] = useState(initial?.note ?? "");

  const path = endpoints.feedback.vote(targetType, targetId);

  const mutation = useMutation({
    mutationFn: (next: MyFeedback | null) =>
      next === null
        ? apiFetch<void>(path, { method: "DELETE" })
        : apiFetch(path, { method: "PUT", body: JSON.stringify(next) }),
    onMutate: (next) => {
      const previous = vote;
      setVote(next);
      return { previous };
    },
    onError: (_error, _next, context) => {
      setVote(context?.previous ?? null);
      toast.error("Your feedback was not saved. Try again.");
    },
  });

  const [seededFrom, setSeededFrom] = useState(initial);
  if (initial !== seededFrom && !mutation.isPending) {
    setSeededFrom(initial);
    setVote(initial ?? null);
  }

  function submit(next: MyFeedback | null) {
    mutation.mutate(next);
  }

  function onThumb(rating: FeedbackRating) {
    if (vote?.rating === rating) {
      submit(null);
      setOpen(false);
      return;
    }
    if (rating === "up") {
      submit({ rating: "up", reasonCodes: [], note: null });
      return;
    }
    setOpen(true);
  }

  function toggleReason(code: FeedbackReasonCode, checked: boolean) {
    setReasons((current) =>
      checked ? [...current, code] : current.filter((value) => value !== code),
    );
  }

  function sendDown() {
    submit({ rating: "down", reasonCodes: reasons, note: note.trim() || null });
    setOpen(false);
  }

  return (
    <div className={cn("mt-3 flex items-center gap-1", className)}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Helpful"
        aria-pressed={vote?.rating === "up"}
        className={vote?.rating === "up" ? "text-primary" : "text-muted-foreground"}
        disabled={mutation.isPending}
        onClick={() => onThumb("up")}
      >
        <ThumbsUp className="size-4" />
      </Button>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Not helpful"
              aria-pressed={vote?.rating === "down"}
              className={
                vote?.rating === "down" ? "text-primary" : "text-muted-foreground"
              }
              disabled={mutation.isPending}
              onClick={(event) => {
                if (vote?.rating === "down") {
                  event.preventDefault();
                  onThumb("down");
                }
              }}
            />
          }
        >
          <ThumbsDown className="size-4" />
        </PopoverTrigger>
        <PopoverContent className="w-80 space-y-3" align="start">
          <p className="text-sm font-medium">What went wrong?</p>
          <div className="space-y-2">
            {reasonsFor(targetType).map((code) => (
              <Label key={code} className="flex items-center gap-2 font-normal">
                <Checkbox
                  checked={reasons.includes(code)}
                  onCheckedChange={(checked) => toggleReason(code, checked === true)}
                />
                {REASON_LABELS[code]}
              </Label>
            ))}
          </div>
          <Textarea
            aria-label="Anything else?"
            placeholder="Anything else? (optional)"
            maxLength={NOTE_MAX_LENGTH}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{NOTE_DISCLOSURE}</p>
          <p className="text-muted-foreground text-xs">
            {note.length}/{NOTE_MAX_LENGTH}
          </p>
          <div className="flex justify-end">
            <Button size="sm" disabled={reasons.length === 0} onClick={sendDown}>
              Send feedback
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
