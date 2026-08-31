"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

/**
 * A tag chip editor: type, then Enter or comma to add; the badge's own button
 * removes one. No client-side count or length cap — `.claude/rules/forms.md` §4
 * limits client checks to required/shape, and the pair count and per-tag length
 * live in the backend (`MAX_TAGS`, `MAX_TAG_CHARS`) as the one place to keep them
 * honest. A 422 surfaces here through `fieldError`, same as every other field.
 *
 * Shared between the edit dialog and the save-from-Ask dialog, both of which need
 * a tag field that accepts values that do not exist yet — unlike the filter bar's
 * `Combobox` in `qa-filters.tsx`, which only ever selects among tags already on
 * the instance, this is a *write* control and must not be limited to that set.
 */
export function TagsEditor({
  id = "qa-tags",
  tags,
  onChange,
  error,
}: {
  id?: string;
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
      <FieldLabel htmlFor={id}>Tags</FieldLabel>
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
        id={id}
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
