/**
 * The API wire contract, mirrored by hand from `backend/app/schemas/`.
 *
 * Hand-written rather than generated: the surface is ~10 shapes that change per
 * milestone, and codegen would need either a running backend at build time or a
 * committed openapi.json that goes stale. See the design spec §2.4.
 *
 * Every field here is camelCase because `ApiModel` applies Pydantic's to_camel
 * alias generator to every request and response schema.
 */

export type ProjectStatus = "pending" | "cloning" | "indexing" | "ready" | "failed";
export type FinishReason = "stop" | "error" | "timeout" | "disconnected";
export type MessageRole = "user" | "assistant";

/** Mirrors `ErrorCode` in `backend/app/core/errors.py`. Add members, never rename. */
export type ErrorCode =
  | "VALIDATION_ERROR"
  | "INTERNAL_ERROR"
  | "INVALID_CREDENTIALS"
  | "INVALID_TOKEN"
  | "TOKEN_EXPIRED"
  | "REFRESH_TOKEN_REUSED"
  | "PASSWORD_CHANGE_REQUIRED"
  | "ADMIN_REQUIRED"
  | "WEAK_PASSWORD"
  | "USER_NOT_FOUND"
  | "EMAIL_ALREADY_EXISTS"
  | "LAST_ADMIN"
  | "INVALID_SORT_FIELD"
  | "RATE_LIMITED"
  | "PROJECT_NOT_FOUND"
  | "NOT_PROJECT_OWNER"
  | "INVALID_REPO_URL"
  | "VECTOR_STORE_UNAVAILABLE"
  | "CONVERSATION_NOT_FOUND"
  | "PROJECT_NOT_READY"
  | "EMBEDDING_MODEL_CHANGED"
  | "LLM_UNAVAILABLE"
  | "MESSAGE_NOT_FOUND"
  | "EXPORT_TOO_LARGE"
  | "CHECKLIST_MODULE_NOT_FOUND"
  | "CHECKLIST_ITEM_NOT_FOUND"
  | "NOT_CHECKLIST_OWNER"
  | "CHANGE_SET_NOT_FOUND"
  | "CHANGE_SET_PENDING"
  | "CHANGE_SET_ALREADY_RESOLVED"
  | "GENERATION_IN_PROGRESS"
  | "MODULE_PATH_NOT_INDEXED";

/** The one error shape the whole API uses (`docs/PRD.md` §5.1). */
export interface ErrorEnvelope {
  detail: {
    code: ErrorCode;
    message: string;
    /** Present on 422 only, keyed by the camelCase field name. */
    fields?: Record<string, string>;
  };
}

export interface UserResponse {
  id: string;
  name: string;
  email: string;
  isAdmin: boolean;
  mustChangePassword: boolean;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** The length bounds a new password must satisfy. Rendered, never hard-coded. */
export interface PasswordPolicyResponse {
  minLength: number;
  maxBytes: number;
}

/** What the backend's POST /auth/login returns. Never forwarded to the browser. */
export interface AccessTokenResponse {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  user: UserResponse;
}

export interface ProjectResponse {
  id: string;
  createdBy: string;
  name: string;
  repoUrl: string;
  branch: string;
  status: ProjectStatus;
  error: string | null;
  lastIndexedCommit: string | null;
  fileCount: number | null;
  chunkCount: number | null;
  embeddingModel: string | null;
  reindexInProgress: boolean;
  createdAt: string;
  updatedAt: string;
}

/** POST /projects/{id}/reindex answers 202 with an outcome flag, never 409. */
export interface ReindexResponse {
  enqueued: boolean;
  project: ProjectResponse;
}

export interface CitationPayload {
  index: number;
  filePath: string;
  startLine: number;
  endLine: number;
  language: string;
  symbol: string | null;
  commitSha: string;
  score: number;
  /** null in the `citations` event (emitted before generation); resolved on the stored message. */
  cited: boolean | null;
}

export interface MessageResponse {
  id: string;
  role: MessageRole;
  content: string;
  citations: CitationPayload[] | null;
  model: string | null;
  finishReason: FinishReason | null;
  createdAt: string;
}

export interface ConversationResponse {
  id: string;
  projectId: string;
  title: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationDetailResponse extends ConversationResponse {
  messages: MessageResponse[];
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  limit: number;
  totalCount: number;
  totalPages: number;
}

export interface ListParams {
  page?: number;
  limit?: number;
  search?: string;
  sort?: string;
  sortDirection?: "asc" | "desc";
}

/* --- SSE payloads (spec §9.5). Mirrors `SSE_EVENT_MODELS`. --- */

export interface StatusEventPayload {
  phase: "queued" | "classifying" | "retrieving" | "grading" | "generating";
}
export interface CitationsEventPayload {
  citations: CitationPayload[];
}
export interface TokenEventPayload {
  text: string;
}
export interface DoneEventPayload {
  messageId: string | null;
  model: string;
  finishReason: FinishReason;
  citedIndexes: number[];
  groundingWarnings: string[];
  intent: "codebase_question" | "conversational" | "out_of_scope";
  retrievalAttempts: number;
}
export interface ErrorEventPayload {
  messageId: string | null;
  code: ErrorCode;
  message: string;
  finishReason: FinishReason;
}

export type ChecklistModuleStatus =
  "empty" | "generating" | "review" | "ready" | "failed";
export type ChecklistItemStatus = "untested" | "pass" | "fail" | "blocked";
export type ChecklistItemSource = "generated" | "manual";
/** Whether a case proves the feature works, or that it refuses what it should. */
export type ChecklistItemKind = "positive" | "negative";
export type ChangeSetOrigin = "generation" | "chat";
export type ChangeSetStatus = "pending" | "applied" | "discarded";

export interface ChecklistModuleResponse {
  id: string;
  projectId: string;
  /** Denormalised by the server so a page of rows needs no second request. */
  projectName: string;
  createdBy: string;
  name: string;
  sourcePath: string;
  status: ChecklistModuleStatus;
  error: string | null;
  indexedGeneration: number | null;
  lastGeneratedAt: string | null;
  itemCount: number;
  passCount: number;
  failCount: number;
  blockedCount: number;
  untestedCount: number;
  /** The project was reindexed after this checklist was built. A prompt, not a block. */
  stale: boolean;
  pendingChangeSetId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ChecklistItemResponse {
  id: string;
  moduleId: string;
  projectId: string;
  feature: string;
  testName: string;
  expectedResult: string;
  /** A human's observation. AskRepo never writes it. */
  currentResult: string | null;
  status: ChecklistItemStatus;
  notes: string | null;
  citations: CitationPayload[] | null;
  source: ChecklistItemSource;
  kind: ChecklistItemKind;
  position: number;
  createdBy: string;
  reviewedBy: string | null;
  reviewedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ChecklistModuleDetailResponse extends ChecklistModuleResponse {
  items: ChecklistItemResponse[];
}

/**
 * One proposed operation. Three shapes in one object, discriminated by `op`: `itemId`
 * is present on `update` and `remove`, the content fields on `add`.
 */
export interface ChangeOperation {
  op: "add" | "update" | "remove";
  id: string;
  rationale: string;
  itemId?: string | null;
  feature?: string | null;
  testName?: string | null;
  expectedResult?: string | null;
  /** Present on `add`; an `update` moves it through `changes` like any other field. */
  kind?: ChecklistItemKind | null;
  citations?: CitationPayload[] | null;
  changes?: Record<string, string> | null;
}

export interface ChecklistChangeSetResponse {
  id: string;
  moduleId: string;
  origin: ChangeSetOrigin;
  messageId: string | null;
  summary: string;
  operations: ChangeOperation[];
  status: ChangeSetStatus;
  resolvedBy: string | null;
  resolvedAt: string | null;
  createdBy: string;
  createdAt: string;
}

export interface ChangeSetApplyResponse {
  changeSet: ChecklistChangeSetResponse;
  items: ChecklistItemResponse[];
  /** Their target item was deleted between proposal and apply; skipped, not failed. */
  skippedOperationIds: string[];
}

export interface ChecklistMessageResponse {
  id: string;
  moduleId: string;
  role: MessageRole;
  content: string;
  citations: CitationPayload[] | null;
  model: string | null;
  finishReason: FinishReason | null;
  createdBy: string;
  createdAt: string;
}

/** The one event M4 adds to the stream. At most once, after the last token. */
export interface ChangeSetEventPayload {
  changeSetId: string;
  summary: string;
  operations: ChangeOperation[];
}

export type MockDataDatasetStatus = "empty" | "generating" | "review" | "ready" | "failed";

export interface MockDataRecordResponse {
  id: string;
  checklistModuleId: string;
  fields: Record<string, string>;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface MockDataDatasetResponse {
  id: string;
  checklistModuleId: string;
  status: MockDataDatasetStatus;
  error: string | null;
  indexedGeneration: number | null;
  lastGeneratedAt: string | null;
  stale: boolean;
  recordCount: number;
  pendingChangeSetId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface MockDataDatasetDetailResponse extends MockDataDatasetResponse {
  records: MockDataRecordResponse[];
}

/** One proposed operation. `fields` (full map) on `add`; `changes` (partial map) on `update`. */
export interface MockDataChangeOperation {
  op: "add" | "update" | "remove";
  id: string;
  rationale: string;
  recordId?: string | null;
  fields?: Record<string, string> | null;
  changes?: Record<string, string> | null;
}

export interface MockDataChangeSetResponse {
  id: string;
  checklistModuleId: string;
  origin: ChangeSetOrigin;
  messageId: string | null;
  summary: string;
  operations: MockDataChangeOperation[];
  status: ChangeSetStatus;
  resolvedBy: string | null;
  resolvedAt: string | null;
  createdBy: string;
  createdAt: string;
}

export interface MockDataChangeSetApplyResponse {
  changeSet: MockDataChangeSetResponse;
  records: MockDataRecordResponse[];
  skippedOperationIds: string[];
}

export interface MockDataMessageResponse {
  id: string;
  checklistModuleId: string;
  role: MessageRole;
  content: string;
  citations: CitationPayload[] | null;
  model: string | null;
  finishReason: FinishReason | null;
  createdBy: string;
  createdAt: string;
}

export interface MockDataChangeSetEventPayload {
  changeSetId: string;
  summary: string;
  operations: MockDataChangeOperation[];
}

export interface ChecklistModuleListParams extends ListParams {
  projectId?: string;
  status?: ChecklistModuleStatus;
}

export interface ChecklistItemListParams extends ListParams {
  projectId?: string;
  moduleId?: string;
  feature?: string;
  status?: ChecklistItemStatus;
  source?: ChecklistItemSource;
  kind?: ChecklistItemKind;
}
