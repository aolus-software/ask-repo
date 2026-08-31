import type { ListParams, QAListParams } from "@/lib/api/types";

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
  qaPairs: {
    list: "/qa-pairs",
    tags: "/qa-pairs/tags",
    export: "/qa-pairs/export",
    detail: (id: string) => `/qa-pairs/${id}`,
    status: (id: string) => `/qa-pairs/${id}/status`,
    rerun: (id: string) => `/qa-pairs/${id}/rerun`,
    acceptRerun: (id: string) => `/qa-pairs/${id}/rerun/accept`,
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
  qaPairs: {
    module: "module",
    status: "status",
    createdAt: "created_at",
    updatedAt: "updated_at",
    lastRunAt: "last_run_at",
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
 * `listQueryString` plus the six QA filters. A new function rather than widening
 * `listQueryString` itself: three other screens call that one and none of them has
 * these filters.
 */
export function qaListQueryString(params: QAListParams): string {
  const base = listQueryString(params);
  const search = new URLSearchParams(base.startsWith("?") ? base.slice(1) : base);
  if (params.projectId) search.set("projectId", params.projectId);
  if (params.module) search.set("module", params.module);
  if (params.tag) search.set("tag", params.tag);
  if (params.source) search.set("source", params.source);
  if (params.status) search.set("status", params.status);
  if (params.createdBy) search.set("createdBy", params.createdBy);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
