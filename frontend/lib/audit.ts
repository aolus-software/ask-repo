import { useTranslations } from "next-intl";

/**
 * The audit trail's event-type vocabulary, mirrored from `AuditEventType` in
 * `backend/app/core/audit.py`. `event_type` is a plain string on the wire — the
 * catalogue is enforced only on the write side, by `tests/test_audit_coverage.py` —
 * so this list is the filter's option set, not a validated enum.
 */
export const AUDIT_EVENT_TYPES = [
  "auth.login.succeeded",
  "auth.login.failed",
  "auth.logout",
  "auth.password.changed",
  "auth.refresh.replayed",
  "auth.session.revoked",
  "user.created",
  "user.updated",
  "user.deactivated",
  "user.password.reset",
  "user.answer_style.updated",
  "project.created",
  "project.reindex.requested",
  "project.deleted",
  "membership.granted",
  "membership.role_changed",
  "membership.revoked",
  "role.created",
  "role.updated",
  "role.deleted",
  "checklist_module.created",
  "checklist_module.updated",
  "checklist_module.deleted",
  "checklist_module.generation.requested",
  "checklist_item.created",
  "checklist_item.updated",
  "checklist_item.result_recorded",
  "checklist_item.deleted",
  "checklist_item.results_cleared",
  "checklist_change_set.applied",
  "checklist_change_set.discarded",
  "checklist.exported",
  "mock_data.generation.requested",
  "mock_data_change_set.applied",
  "mock_data_change_set.discarded",
  "mock_data_record.deleted",
  "mock_data.exported",
  "conversation.created",
  "conversation.deleted",
] as const;

/**
 * The translated label for an event type, read from `audit.events` in the catalogue.
 * The catalogue key is the event name with `.` replaced by `_`; an event type this
 * client has never heard of renders as the raw name rather than a missing-key error,
 * since the backend may ship one before the frontend catalogue does.
 */
export function useAuditEventLabel(): (eventType: string) => string {
  const t = useTranslations("audit.events");
  return (eventType) => {
    const key = eventType.replaceAll(".", "_");
    return t.has(key as never) ? t(key as never) : eventType;
  };
}

/** A changed field's label (`isAdmin` → "Is admin"), derived when the catalogue has none. */
export function useAuditFieldLabel(): (field: string) => string {
  const t = useTranslations("audit.fields");
  return (field) => (t.has(field as never) ? t(field as never) : humanizeField(field));
}

/** "isAdmin" -> "Is admin": the fallback for a field the catalogue does not name. */
function humanizeField(key: string): string {
  const spaced = key.replace(/([A-Z])/g, " $1").trim();
  const lower = spaced.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
