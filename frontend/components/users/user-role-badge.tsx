import { Badge } from "@/components/ui/badge";

/**
 * Role colour decided here and nowhere else (`.claude/rules/design-system.md` §5) —
 * previously an inline `bg-primary` class at the table call site
 * (`docs/ui-audit-findings.md` §U4.1). `info` is the token role reserved for exactly
 * this: a badge that is not a project or module status.
 */
export function UserRoleBadge({ isAdmin }: { isAdmin: boolean }) {
  return isAdmin ? (
    <Badge className="bg-info text-info-foreground">Admin</Badge>
  ) : (
    <Badge variant="outline">Member</Badge>
  );
}
