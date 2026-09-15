"use client";

import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAddMember } from "@/hooks/use-member-mutations";
import { useMembers } from "@/hooks/use-members";
import { useRoleOptions } from "@/hooks/use-role-options";
import { useUsers } from "@/hooks/use-users";
import { SORT } from "@/lib/api/endpoints";
import type { UserResponse } from "@/lib/api/types";

const DEFAULT_ROLE = "viewer";

/**
 * Grant a user a role on this project. Two fields, so a dialog (`forms.md` §1).
 *
 * The user picker excludes anyone who already has a role here — the backend would
 * otherwise refuse with `409 MEMBERSHIP_EXISTS`, and there is nothing to add for that
 * user beyond changing their existing row's role, which the table's own Select does.
 */
export function AddMemberDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [userId, setUserId] = useState<string | null>(null);
  const [role, setRole] = useState(DEFAULT_ROLE);
  const mutation = useAddMember(projectId);
  const roleOptions = useRoleOptions();
  const members = useMembers(projectId, open);
  const usersQuery = useUsers({
    limit: 100,
    sort: SORT.users.name,
    sortDirection: "asc",
  });

  const memberIds = new Set((members.data ?? []).map((member) => member.userId));
  const candidates = (usersQuery.data?.items ?? []).filter(
    (user) => !memberIds.has(user.id),
  );
  const selectedUser = candidates.find((user) => user.id === userId) ?? null;

  function reset() {
    setUserId(null);
    setRole(DEFAULT_ROLE);
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!userId) return;

    mutation.mutate(
      { userId, role },
      {
        onSuccess: () => {
          toast.success("Member added");
          reset();
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title="Add a member"
      description="Grant a user access to this project."
      submitLabel="Add member"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="add-member-user">User</FieldLabel>
        <Combobox
          items={candidates}
          value={selectedUser}
          onValueChange={(next: UserResponse | null) => setUserId(next?.id ?? null)}
          itemToStringLabel={(user: UserResponse) => user.name}
        >
          <ComboboxInput
            id="add-member-user"
            className="w-full"
            placeholder={usersQuery.isLoading ? "Loading people…" : "Search people"}
            aria-label="User"
          />
          <ComboboxContent>
            <ComboboxEmpty>
              {usersQuery.isLoading ? "Loading…" : "No user matches."}
            </ComboboxEmpty>
            <ComboboxList>
              {(user: UserResponse) => (
                <ComboboxItem key={user.id} value={user} className="justify-between">
                  <span className="truncate">{user.name}</span>
                  <span className="text-muted-foreground truncate text-xs">
                    {user.email}
                  </span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </Field>

      <Field>
        <FieldLabel htmlFor="add-member-role">Role</FieldLabel>
        <Select
          value={role}
          onValueChange={(value: string | null | undefined) => {
            if (value) setRole(value);
          }}
        >
          <SelectTrigger id="add-member-role" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roleOptions.map((option) => (
              <SelectItem key={option.name} value={option.name}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    </FormDialog>
  );
}
