import { networkError, parseApiError } from "@/lib/api/errors";

/**
 * The browser's only route to the API: same-origin, through the proxy. It carries no
 * token and knows nothing about auth — the proxy attaches the bearer.
 */
async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      credentials: "same-origin",
      headers: {
        ...(init?.body ? { "content-type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    // An abort is the caller's own doing (a cancelled answer stream); everything else
    // is the network failing before a Response existed.
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw networkError();
  }
  if (!response.ok) throw await parseApiError(response);
  return response;
}

/** Typed JSON. A 204 resolves to `undefined` cast to T, which every caller ignores. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The raw response, for the one caller that needs a stream (the answer endpoint). */
export function apiFetchRaw(path: string, init?: RequestInit): Promise<Response> {
  return request(path, init);
}
