import type {
  AuditEventListParams,
  ChecklistItemListParams,
  ChecklistModuleListParams,
  ListParams,
  NotificationListParams,
} from "@/lib/api/types";

/**
 * Every API path in one module. A string literal at a call site is how the
 * snake_case sort trap below gets rediscovered one screen at a time.
 */
export const endpoints = {
  auth: {
    login: "/auth/login",
    refresh: "/auth/refresh",
    logout: "/auth/logout",
    logoutAll: "/auth/logout-all",
    changePassword: "/auth/change-password",
    passwordPolicy: "/auth/password-policy",
    me: "/auth/me",
  },
  users: {
    list: "/users",
    detail: (id: string) => `/users/${id}`,
    resetPassword: (id: string) => `/users/${id}/reset-password`,
  },
  projects: {
    list: "/projects",
    detail: (id: string) => `/projects/${id}`,
    reindex: (id: string) => `/projects/${id}/reindex`,
    indexedPaths: (id: string) => `/projects/${id}/indexed-paths`,
  },
  conversations: {
    list: "/conversations",
    detail: (id: string) => `/conversations/${id}`,
    messages: (id: string) => `/conversations/${id}/messages`,
  },
  checklistModules: {
    list: "/checklist-modules",
    detail: (id: string) => `/checklist-modules/${id}`,
    generate: (id: string) => `/checklist-modules/${id}/generate`,
    changeSets: (id: string) => `/checklist-modules/${id}/change-sets`,
    messages: (id: string) => `/checklist-modules/${id}/messages`,
  },
  checklistItems: {
    list: "/checklist-items",
    export: "/checklist-items/export",
    clearResults: "/checklist-items/clear-results",
    detail: (id: string) => `/checklist-items/${id}`,
    result: (id: string) => `/checklist-items/${id}/result`,
  },
  checklistChangeSets: {
    apply: (id: string) => `/checklist-change-sets/${id}/apply`,
    discard: (id: string) => `/checklist-change-sets/${id}/discard`,
  },
  mockData: {
    detail: (moduleId: string) => `/checklist-modules/${moduleId}/mock-data`,
    generate: (moduleId: string) =>
      `/checklist-modules/${moduleId}/mock-data-generations`,
    changeSets: (moduleId: string) =>
      `/checklist-modules/${moduleId}/mock-data-change-sets`,
    messages: (moduleId: string) => `/checklist-modules/${moduleId}/mock-data-messages`,
    exportJson: (moduleId: string) =>
      `/checklist-modules/${moduleId}/mock-data/export.json`,
    exportXlsx: (moduleId: string) =>
      `/checklist-modules/${moduleId}/mock-data/export.xlsx`,
  },
  mockDataRecords: {
    detail: (id: string) => `/mock-data-records/${id}`,
  },
  mockDataChangeSets: {
    apply: (id: string) => `/mock-data-change-sets/${id}/apply`,
    discard: (id: string) => `/mock-data-change-sets/${id}/discard`,
  },
  roles: {
    list: "/roles",
    detail: (id: string) => `/roles/${id}`,
  },
  permissions: {
    catalogue: "/permissions",
  },
  members: {
    list: (projectId: string) => `/projects/${projectId}/members`,
    detail: (projectId: string, userId: string) =>
      `/projects/${projectId}/members/${userId}`,
  },
  auditEvents: {
    list: "/audit-events",
    detail: (id: string) => `/audit-events/${id}`,
  },
  notifications: {
    list: "/notifications",
    unreadCount: "/notifications/unread-count",
    markAllRead: "/notifications/mark-all-read",
    markRead: (id: string) => `/notifications/${id}/read`,
    preferences: "/notification-preferences",
  },
} as const;

/**
 * Sort values are matched against snake_case COLUMN names on the backend
 * (`ProjectRepository.SORTABLE_FIELDS`, `backend/app/repositories/project.py:34`),
 * while every other field on the wire is camelCase. Sending `updatedAt` earns a
 * 422 INVALID_SORT_FIELD. Reported, not fixed — see the design spec §2.7.
 */
export const SORT = {
  projects: {
    name: "name",
    status: "status",
    createdAt: "created_at",
    updatedAt: "updated_at",
  },
  users: {
    name: "name",
    email: "email",
    createdAt: "created_at",
    lastLoginAt: "last_login_at",
  },
  conversations: { title: "title", createdAt: "created_at", updatedAt: "updated_at" },
  checklistModules: {
    name: "name",
    status: "status",
    createdAt: "created_at",
    updatedAt: "updated_at",
    lastGeneratedAt: "last_generated_at",
  },
  checklistItems: {
    feature: "feature",
    testName: "test_name",
    status: "status",
    position: "position",
    createdAt: "created_at",
    updatedAt: "updated_at",
  },
} as const;

/** Serialise list params, dropping empties so the cache key stays stable. */
export function listQueryString(params: ListParams): string {
  const search = new URLSearchParams();
  if (params.page && params.page > 1) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));
  if (params.search) search.set("search", params.search);
  if (params.sort) search.set("sort", params.sort);
  if (params.sortDirection) search.set("sortDirection", params.sortDirection);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * The path picker's two params. `search` wins when both are set — the server ignores
 * `path` on a search, and sending both would suggest otherwise.
 */
export function indexedPathsQueryString(params: {
  path?: string;
  search?: string;
}): string {
  const search = new URLSearchParams();
  if (params.search) search.set("search", params.search);
  else if (params.path) search.set("path", params.path);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** `listQueryString` plus the two module filters. */
export function checklistModuleListQueryString(
  params: ChecklistModuleListParams,
): string {
  const search = new URLSearchParams(listQueryString(params).replace(/^\?/, ""));
  if (params.projectId) search.set("projectId", params.projectId);
  if (params.status) search.set("status", params.status);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** `listQueryString` plus the five grid filters. */
export function checklistItemListQueryString(params: ChecklistItemListParams): string {
  const search = new URLSearchParams(listQueryString(params).replace(/^\?/, ""));
  if (params.projectId) search.set("projectId", params.projectId);
  if (params.moduleId) search.set("moduleId", params.moduleId);
  if (params.feature) search.set("feature", params.feature);
  if (params.status) search.set("status", params.status);
  if (params.source) search.set("source", params.source);
  if (params.kind) search.set("kind", params.kind);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** `listQueryString` plus the audit trail's own filters. */
export function auditEventListQueryString(params: AuditEventListParams): string {
  const search = new URLSearchParams(listQueryString(params).replace(/^\?/, ""));
  if (params.eventType) search.set("eventType", params.eventType);
  if (params.actorUserId) search.set("actorUserId", params.actorUserId);
  if (params.projectId) search.set("projectId", params.projectId);
  if (params.outcome) search.set("outcome", params.outcome);
  if (params.occurredFrom) search.set("occurredFrom", params.occurredFrom);
  if (params.occurredTo) search.set("occurredTo", params.occurredTo);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * `listQueryString` plus the notifications page's own filters. `unreadOnly` is set
 * only when true — the URL never carries `unreadOnly=false`, so a truthy check here
 * is enough regardless of whether the value arrived as a real boolean or as the
 * string a URL search param round-trips through.
 */
export function notificationListQueryString(params: NotificationListParams): string {
  const search = new URLSearchParams(listQueryString(params).replace(/^\?/, ""));
  if (params.eventType) search.set("eventType", params.eventType);
  if (params.projectId) search.set("projectId", params.projectId);
  if (params.unreadOnly) search.set("unreadOnly", "true");
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
