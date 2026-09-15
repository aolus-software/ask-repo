"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldLabel } from "@/components/ui/field";
import type { PermissionGroupResponse } from "@/lib/api/types";

/**
 * The checkbox grid. Groups and their labels come straight from `GET /permissions`
 * (`PermissionCatalogResponse.groups`) — never derived client-side by splitting a
 * permission string on `.`, per `.claude/rules/rag.md`-style server-owned labelling
 * (the catalogue is the server's enum, and a second copy of the human names would
 * drift from it).
 */
export function PermissionMatrix({
  groups,
  selected,
  onToggle,
  disabled = false,
}: {
  groups: PermissionGroupResponse[];
  selected: Set<string>;
  onToggle: (permission: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.label} className="space-y-3">
          <h3 className="text-sm font-semibold">{group.label}</h3>
          <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
            {group.permissions.map((permission) => (
              <Field key={permission} orientation="horizontal">
                <Checkbox
                  id={`permission-${permission}`}
                  checked={selected.has(permission)}
                  disabled={disabled}
                  onCheckedChange={() => onToggle(permission)}
                />
                <FieldLabel
                  htmlFor={`permission-${permission}`}
                  className="font-mono text-sm font-normal"
                >
                  {permission}
                </FieldLabel>
              </Field>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
