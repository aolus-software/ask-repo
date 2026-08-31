"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MoreHorizontal, Pencil, RotateCw, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Answer } from "@/components/ask/answer";
import { Sources } from "@/components/ask/sources";
import { NotFound } from "@/components/feedback/not-found";
import { StatusBadge } from "@/components/feedback/status-badge";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { FormDialog } from "@/components/form/form-dialog";
import { FormError } from "@/components/form/form-error";
import { QAStatusControl } from "@/components/qa/qa-status-control";
import { RerunPanel } from "@/components/qa/rerun-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useProject } from "@/hooks/use-projects";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { fieldError, isApiError } from "@/lib/api/errors";
import type { QAPairDetailResponse } from "@/lib/api/types";
import { canManageQAPair } from "@/lib/can";
import { formatAbsolute, formatRelative } from "@/lib/dates";
import { keys } from "@/lib/query/keys";
import { qaStatusLabel, qaStatusTone } from "@/lib/status";

/**
 * A tag chip editor: type, then Enter or comma to add; the badge's own button
 * removes one. No client-side count or length cap — `.claude/rules/forms.md` §4
 * limits client checks to required/shape, and the pair count and per-tag length
 * live in the backend (`MAX_TAGS`, `MAX_TAG_CHARS`) as the one place to keep them
 * honest. A 422 surfaces here through `fieldError`, same as every other field.
 */
function TagsEditor({
  tags,
  onChange,
  error,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  error?: string;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const value = draft.trim();
    if (value && !tags.includes(value)) onChange([...tags, value]);
    setDraft("");
  }

  return (
    <Field>
      <FieldLabel htmlFor="qa-edit-tags">Tags</FieldLabel>
      {tags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <Badge key={tag} variant="outline" className="gap-1">
              {tag}
              <button
                type="button"
                aria-label={`Remove tag ${tag}`}
                onClick={() => onChange(tags.filter((existing) => existing !== tag))}
              >
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      ) : null}
      <Input
        id="qa-edit-tags"
        value={draft}
        placeholder="Add a tag, then press Enter"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
        aria-invalid={Boolean(error)}
      />
      {error ? <FieldError>{error}</FieldError> : null}
    </Field>
  );
}

/**
 * Module, question and tags — never `answer`, which only ever comes from a model,
 * and never `referenceAnswer`, which has its own inline editor beside the result
 * (`docs/superpowers/specs/2026-08-31-m4-qa-list-design.md` §7.2). Three simple
 * fields plus a tag picker: a `FormDialog`, per `.claude/rules/forms.md` §1.
 */
function EditQAPairDialog({
  pair,
  open,
  onOpenChange,
}: {
  pair: QAPairDetailResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();

  // Seeded during render, keyed on the pair's id — never from an effect
  // (`forms.md` §6). Reopening on a different pair re-seeds.
  const [seededId, setSeededId] = useState<string | null>(null);
  const [values, setValues] = useState({
    module: pair.module ?? "",
    question: pair.question,
    tags: pair.tags,
  });
  const [questionError, setQuestionError] = useState<string | undefined>();

  if (seededId !== pair.id) {
    setSeededId(pair.id);
    setValues({ module: pair.module ?? "", question: pair.question, tags: pair.tags });
    setQuestionError(undefined);
  }

  const mutation = useMutation({
    mutationFn: (input: { module: string | null; question: string; tags: string[] }) =>
      apiFetch<QAPairDetailResponse>(endpoints.qaPairs.detail(pair.id), {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("QA pair updated");
      onOpenChange(false);
    },
  });

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Required and shape only — the 4000-char ceiling is the backend's
    // (`QAPairUpdateRequest.question`), not restated here.
    if (!values.question.trim()) {
      setQuestionError("Enter a question.");
      return;
    }
    setQuestionError(undefined);

    mutation.mutate({
      module: values.module.trim() || null,
      question: values.question,
      tags: values.tags,
    });
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Edit QA pair"
      submitLabel="Save changes"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="qa-edit-module">Module</FieldLabel>
        <Input
          id="qa-edit-module"
          value={values.module}
          onChange={(event) => setValues({ ...values, module: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "module"))}
        />
        {fieldError(mutation.error, "module") ? (
          <FieldError>{fieldError(mutation.error, "module")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="qa-edit-question">
          Question <span className="text-danger">*</span>
        </FieldLabel>
        <Textarea
          id="qa-edit-question"
          rows={4}
          value={values.question}
          onChange={(event) => setValues({ ...values, question: event.target.value })}
          aria-invalid={Boolean(
            questionError ?? fieldError(mutation.error, "question"),
          )}
        />
        {(questionError ?? fieldError(mutation.error, "question")) ? (
          <FieldError>
            {questionError ?? fieldError(mutation.error, "question")}
          </FieldError>
        ) : null}
      </Field>

      <TagsEditor
        tags={values.tags}
        onChange={(tags) => setValues({ ...values, tags })}
        error={fieldError(mutation.error, "tags")}
      />
    </FormDialog>
  );
}

/**
 * `referenceAnswer` is the one field a caller edits without leaving the page — it
 * has no fixed shell in `.claude/rules/forms.md` because it is not a dialog or a
 * page form, it is a single field beside the read-only `answer` it is judged
 * against. Owner-gated, same as the actions menu.
 */
function ExpectedResultCard({
  pair,
  canManage,
}: {
  pair: QAPairDetailResponse;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(pair.referenceAnswer ?? "");

  const mutation = useMutation({
    mutationFn: (referenceAnswer: string) =>
      apiFetch<QAPairDetailResponse>(endpoints.qaPairs.detail(pair.id), {
        method: "PATCH",
        body: JSON.stringify({ referenceAnswer: referenceAnswer || null }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      setEditing(false);
    },
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Expected result</CardTitle>
        {canManage && !editing ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Edit expected result"
            onClick={() => {
              setDraft(pair.referenceAnswer ?? "");
              setEditing(true);
            }}
          >
            <Pencil className="size-4" />
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="space-y-2">
            <Textarea
              rows={10}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-label="Expected result"
              disabled={mutation.isPending}
            />
            <FormError error={mutation.error} />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={mutation.isPending}
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(draft)}
              >
                {mutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : null}
                Save
              </Button>
            </div>
          </div>
        ) : pair.referenceAnswer ? (
          <p className="text-base whitespace-pre-wrap">{pair.referenceAnswer}</p>
        ) : (
          <p className="text-muted-foreground text-sm">Not set.</p>
        )}
      </CardContent>
    </Card>
  );
}

function ResultCard({ pair }: { pair: QAPairDetailResponse }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Result</CardTitle>
      </CardHeader>
      <CardContent>
        {pair.answer ? (
          <>
            <Answer content={pair.answer} />
            <Sources citations={pair.citations ?? []} citedIndexes={[]} />
            {pair.lastRunAt ? (
              <p className="text-muted-foreground mt-4 text-sm">
                Last run{" "}
                <span title={formatAbsolute(pair.lastRunAt)}>
                  {formatRelative(pair.lastRunAt)}
                </span>
                {pair.model ? ` · ${pair.model}` : ""}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground text-sm">Not run yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Edit, Re-run and Delete, gated by `canManageQAPair` — the same ownership rule the
 * backend enforces on `PATCH`/`POST .../rerun`/`DELETE /qa-pairs/{id}`.
 */
function QAPairActionsMenu({
  pair,
  onRerun,
}: {
  pair: QAPairDetailResponse;
  onRerun: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () =>
      apiFetch<void>(endpoints.qaPairs.detail(pair.id), { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.qaPairs.all });
      toast.success("QA pair deleted");
      router.push("/qa");
    },
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Actions for ${pair.module ?? "this QA pair"}`}
            />
          }
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => setEditing(true)}>
            <Pencil className="size-4" />
            Edit
          </DropdownMenuItem>
          <DropdownMenuItem onClick={onRerun}>
            <RotateCw className="size-4" />
            Re-run
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setConfirmingDelete(true)}>
            <Trash2 className="size-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <EditQAPairDialog pair={pair} open={editing} onOpenChange={setEditing} />

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete this QA pair?"
        description="It is shared with everyone on the instance, and this cannot be undone."
        confirmLabel="Delete"
        isPending={remove.isPending}
        error={remove.error}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

export function QAPairScreen({ id }: { id: string }) {
  const user = useSession();
  // Also true whenever the pair loads with a pending run already stored — that is
  // the visible payoff of holding a re-run server-side (spec §2.5): it survives a
  // reload, a closed laptop, or a different browser, so the panel renders without
  // anyone having pressed the button in this session.
  const [rerunTriggered, setRerunTriggered] = useState(false);
  const query = useQuery({
    queryKey: keys.qaPairs.detail(id),
    queryFn: () => apiFetch<QAPairDetailResponse>(endpoints.qaPairs.detail(id)),
    enabled: Boolean(id),
  });

  const project = useProject(query.data?.projectId ?? "");

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (query.error) {
    // A pair you may not edit still answers 403 on the write; reading one that does
    // not exist answers 404. Existence is public here, same as a project.
    if (isApiError(query.error) && query.error.status === 404) {
      return (
        <NotFound message="That QA pair does not exist, or it has been deleted." />
      );
    }
    return <NotFound message={(query.error as Error).message} />;
  }

  const pair = query.data;
  if (!pair) return <NotFound />;

  const canManage = canManageQAPair(user, pair);
  const showRerunPanel = rerunTriggered || Boolean(pair.pendingRun);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-tight">
              {pair.module ?? "Untitled"}
            </h1>
            <StatusBadge
              tone={qaStatusTone(pair.status)}
              label={qaStatusLabel(pair.status)}
            />
          </div>
          <p className="text-muted-foreground mt-1 text-base">
            {project.data ? (
              <Link href={`/projects/${pair.projectId}`} className="hover:underline">
                {project.data.name}
              </Link>
            ) : (
              pair.projectId
            )}
            {pair.source === "generated" ? " · Generated" : " · Manual"}
          </p>
          {pair.tags.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {pair.tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>
          ) : null}
        </div>
        {canManage ? (
          <QAPairActionsMenu pair={pair} onRerun={() => setRerunTriggered(true)} />
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Question</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-base">{pair.question}</p>
        </CardContent>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <ExpectedResultCard pair={pair} canManage={canManage} />
        {showRerunPanel ? null : <ResultCard pair={pair} />}
      </div>

      {showRerunPanel ? (
        <RerunPanel pair={pair} onClose={() => setRerunTriggered(false)} />
      ) : null}

      <QAStatusControl
        pairId={pair.id}
        status={pair.status}
        reviewedBy={pair.reviewedBy}
        reviewedAt={pair.reviewedAt}
      />
    </div>
  );
}
