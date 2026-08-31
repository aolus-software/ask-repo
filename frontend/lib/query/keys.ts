import type { ListParams, QAListParams } from "@/lib/api/types";

/**
 * Every query key, in one module. Prefix invalidation after a mutation
 * (`.claude/rules/forms.md` §8) is then `invalidateQueries({ queryKey: keys.projects.all })`
 * and cannot be spelled two ways in two components.
 */
export const keys = {
  me: ["me"] as const,
  passwordPolicy: ["password-policy"] as const,
  projects: {
    all: ["projects"] as const,
    list: (params: ListParams) => ["projects", "list", params] as const,
    detail: (id: string) => ["projects", "detail", id] as const,
  },
  conversations: {
    all: ["conversations"] as const,
    list: (params: ListParams & { projectId?: string }) =>
      ["conversations", "list", params] as const,
    detail: (id: string) => ["conversations", "detail", id] as const,
  },
  users: {
    all: ["users"] as const,
    list: (params: ListParams) => ["users", "list", params] as const,
    detail: (id: string) => ["users", "detail", id] as const,
  },
  qaPairs: {
    all: ["qa-pairs"] as const,
    list: (params: QAListParams) => ["qa-pairs", "list", params] as const,
    detail: (id: string) => ["qa-pairs", "detail", id] as const,
    tags: ["qa-pairs", "tags"] as const,
  },
};
