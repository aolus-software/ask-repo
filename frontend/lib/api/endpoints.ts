import type {
  ChecklistItemListParams,
  ChecklistModuleListParams,
  ListParams,
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
    detail: (id: string) => `/checklist-items/${id}`,
    result: (id: string) => `/checklist-items/${id}/result`,
  },
  checklistChangeSets: {
    apply: (id: string) => `/checklist-change-sets/${id}/apply`,
    discard: (id: string) => `/checklist-change-sets/${id}/discard`,
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
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
