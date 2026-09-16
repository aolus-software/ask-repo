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
  "user.created",
  "user.updated",
  "user.deactivated",
  "user.password.reset",
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
 * A readable label for an event type, derived rather than looked up: `.` and `_`
 * become spaces and the first letter is capitalised — "checklist_module.deleted"
 * reads as "Checklist module deleted". Derived, not a lookup table, so a new event
 * name added to the catalogue never needs a matching entry here.
 */
export function auditEventLabel(eventType: string): string {
  const words = eventType.replace(/[._]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
