"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { TagsEditor } from "@/components/qa/tags-editor";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { fieldError } from "@/lib/api/errors";
import type { QAPairDetailResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * Publishes a finished answer to the shared QA List.
 *
 * Posts `{messageId, module, tags}` to `POST /qa-pairs` — never the answer text.
 * The server resolves the message through its conversation and copies the
 * question, the answer and its citations out of the rows itself
 * (`docs/superpowers/specs/2026-08-31-m4-qa-list-design.md` §2.6). A request body
 * carrying the answer text would have no way to be checked against
 * `finishReason`, because a truncated answer and a short one are the same string
 * — the server reading the row is the only enforcement point for that guard, so
 * the client never sends anything the server would have to trust blindly.
 *
 * A `FormDialog` rather than a page, per `.claude/rules/forms.md` §1: two
 * optional fields, and no reason to navigate away from a conversation in
 * progress. The `409 ANSWER_INCOMPLETE` the server can still return here (a
 * message that finished when the answer action was disabled, but no longer
 * does by the time this submits) renders as the shell's form-level error — it
 * carries no `fields` map, so `FormError` shows it as a banner rather than
 * routing it to an input that was never wrong.
 */
export function SaveToQADialog({
  messageId,
  open,
  onOpenChange,
}: {
  messageId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();

  // Seeded on open rather than from an effect (`forms.md` §6): the dialog stays
  // mounted between opens, and resetting only when it was closed keeps a second
  // save on the same message from reopening with the first attempt's draft.
  const [seededFor, setSeededFor] = useState<string | null>(null);
  const [values, setValues] = useState<{ module: string; tags: string[] }>({
    module: "",
    tags: [],
  });

  if (open && seededFor !== messageId) {
    setSeededFor(messageId);
    setValues({ module: "", tags: [] });
  }

  const mutation = useMutation({
    mutationFn: (input: { module: string | null; tags: string[] }) =>
      apiFetch<QAPairDetailResponse>(endpoints.qaPairs.list, {
        method: "POST",
        body: JSON.stringify({ messageId, ...input }),
      }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("Saved to the QA List", {
        description: (
          <Link href={`/qa/${created.id}`} className="underline">
            View it in the QA List
          </Link>
        ),
      });
      onOpenChange(false);
    },
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate({ module: values.module.trim() || null, tags: values.tags });
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Save to QA List"
      description="Publishes this answer to everyone on the instance as a reviewable pair."
      submitLabel="Save"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="qa-save-module">Module</FieldLabel>
        <Input
          id="qa-save-module"
          value={values.module}
          onChange={(event) => setValues({ ...values, module: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "module"))}
        />
        {fieldError(mutation.error, "module") ? (
          <FieldError>{fieldError(mutation.error, "module")}</FieldError>
        ) : null}
      </Field>

      <TagsEditor
        id="qa-save-tags"
        tags={values.tags}
        onChange={(tags) => setValues({ ...values, tags })}
        error={fieldError(mutation.error, "tags")}
      />
    </FormDialog>
  );
}
