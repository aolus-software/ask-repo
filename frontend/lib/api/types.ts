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
  | "LLM_UNAVAILABLE";

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
  phase: "queued" | "rewriting" | "retrieving" | "generating";
}
export interface CitationsEventPayload {
  citations: CitationPayload[];
}
export interface TokenEventPayload {
  text: string;
}
export interface DoneEventPayload {
  messageId: string;
  model: string;
  finishReason: FinishReason;
  citedIndexes: number[];
  groundingWarnings: string[];
}
export interface ErrorEventPayload {
  messageId: string;
  code: ErrorCode;
  message: string;
  finishReason: FinishReason;
}
