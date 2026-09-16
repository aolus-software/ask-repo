/**
 * Mirrors the backend's permission gate — it does NOT replace it. A 403
 * INSUFFICIENT_ROLE or a 404 still surfaces as an error; this only decides what to
 * show.
 *
 * The client never reconstructs what a role means. The server sends the caller's
 * effective permission set per project (`ProjectResponse.permissions`) and this asks
 * whether a string is in it. That is what lets an administrator create a custom role
 * at runtime and have it work with no frontend release — a hardcoded mirror of the
 * matrix would defeat the whole point of `/settings/roles`.
 */

/** Permission strings, as the backend's `app/core/permissions.py` defines them. */
export const PERMISSION = {
  PROJECT_READ: "project.read",
  PROJECT_UPDATE: "project.update",
  PROJECT_DELETE: "project.delete",
  PROJECT_REINDEX: "project.reindex",
  QUESTION_ASK: "question.ask",
  CHECKLIST_READ: "checklist.read",
  MODULE_CREATE: "module.create",
  MODULE_EDIT: "module.edit",
  MODULE_DELETE: "module.delete",
  GENERATE_RUN: "generate.run",
  CHANGESET_APPLY: "changeset.apply",
  ITEM_EDIT: "item.edit",
  RESULT_RECORD: "result.record",
  MOCKDATA_READ: "mockdata.read",
  MOCKDATA_EDIT: "mockdata.edit",
  MEMBERSHIP_READ: "membership.read",
  MEMBERSHIP_GRANT: "membership.grant",
  MEMBERSHIP_REVOKE: "membership.revoke",
} as const;

export type Permission = (typeof PERMISSION)[keyof typeof PERMISSION];

/** Anything the API returned carrying the caller's effective permissions. */
export interface HasPermissions {
  permissions: string[];
}

/** Whether this caller may perform `permission` on this project. */
export function can(subject: HasPermissions, permission: Permission): boolean {
  return subject.permissions.includes(permission);
}
