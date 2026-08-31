/**
 * Mirrors the backend's destructive-operation gate — it does NOT replace it. A 403
 * NOT_PROJECT_OWNER still surfaces as an error; this only decides what to show.
 *
 * `created_by` is attribution and a destructive-op gate, never read scope
 * (`docs/PRD.md` §4.1). Do not reuse this to filter a list.
 */
export function canManageProject(
  user: { id: string; isAdmin: boolean },
  project: { createdBy: string },
): boolean {
  return user.isAdmin || project.createdBy === user.id;
}

/**
 * Mirrors the backend's gate on editing, deleting and re-running a pair. It does
 * NOT cover setting the status — that is open to every user by design
 * (`docs/PRD.md:338`), so do not reuse this to hide the status control.
 */
export function canManageQAPair(
  user: { id: string; isAdmin: boolean },
  pair: { createdBy: string },
): boolean {
  return user.isAdmin || pair.createdBy === user.id;
}
