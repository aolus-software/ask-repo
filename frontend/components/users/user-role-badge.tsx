import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";

/**
 * Role colour decided here and nowhere else (`.claude/rules/design-system.md` §5) —
 * previously an inline `bg-primary` class at the table call site
 * (`docs/audit-finding-solved-logs.md` §U4.1). `info` is the token role reserved for exactly
 * this: a badge that is not a project or module status.
 */
export function UserRoleBadge({ isAdmin }: { isAdmin: boolean }) {
  const t = useTranslations("settings.users.roleBadge");
  return isAdmin ? (
    <Badge className="bg-info text-info-foreground">{t("admin")}</Badge>
  ) : (
    <Badge variant="outline">{t("member")}</Badge>
  );
}
