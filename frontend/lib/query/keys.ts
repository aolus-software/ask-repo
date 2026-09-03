import type {
  ChecklistItemListParams,
  ChecklistModuleListParams,
  ListParams,
} from "@/lib/api/types";

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
  checklistModules: {
    all: ["checklist-modules"] as const,
    list: (params: ChecklistModuleListParams) => ["checklist-modules", "list", params] as const,
    detail: (id: string) => ["checklist-modules", "detail", id] as const,
  },
  checklistItems: {
    all: ["checklist-items"] as const,
    list: (params: ChecklistItemListParams) => ["checklist-items", "list", params] as const,
  },
  checklistChangeSets: {
    all: ["checklist-change-sets"] as const,
    forModule: (moduleId: string) => ["checklist-change-sets", moduleId] as const,
  },
  checklistMessages: {
    forModule: (moduleId: string) => ["checklist-messages", moduleId] as const,
  },
};
