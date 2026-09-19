import { Lock } from "lucide-react";

/**
 * A role's name, with a lock affordance for the three built-in roles. Modelled on
 * `user-role-badge.tsx` — the lock is what tells an admin, before they even open the
 * row, that viewer/editor/owner cannot be edited or deleted (`.claude/rules/design-system.md` §5).
 */
export function RoleBadge({ name, isSystem }: { name: string; isSystem: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      {name}
      {isSystem ? (
        <Lock
          className="text-muted-foreground size-4"
          aria-label="Built-in role, cannot be edited"
        />
      ) : null}
    </span>
  );
}
