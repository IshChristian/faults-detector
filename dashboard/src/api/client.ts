/**
 * Fetch wrapper for the VisionGuard API.
 *
 * - The access token lives only in memory. The refresh token lives only in the httpOnly
 *   `vg_refresh` cookie; JavaScript never reads or stores it.
 * - On a 401 the client refreshes once (concurrent 401s share one in-flight refresh), then retries.
 * - Problem+json errors are thrown as ApiProblem.
 */
const API_BASE = "/api/v1";

export class ApiProblem extends Error {
  constructor(
    public status: number,
    public type: string,
    public title: string,
    public detail?: string,
  ) {
    super(detail || title);
    this.name = "ApiProblem";
  }
}

export type SessionPayload = {
  access_token: string;
  user: import("../auth/types").User;
};

let accessToken: string | null = null;
let refreshing: Promise<SessionPayload | null> | null = null;
let onUnauthenticated: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
}

/** The current in-memory access token (read at request time so long-lived callers see refreshes). */
export function getAccessToken(): string | null {
  return accessToken;
}

export function configureClient(opts: { onUnauthenticated: () => void }) {
  onUnauthenticated = opts.onUnauthenticated;
}

function url(path: string): string {
  // Absolute URL so it also works outside a browser (tests run on Node's fetch).
  return new URL(API_BASE + path, window.location.origin).toString();
}

async function toProblem(res: Response): Promise<ApiProblem> {
  let body: { type?: string; title?: string; detail?: string } = {};
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  return new ApiProblem(res.status, body.type ?? "about:blank", body.title ?? res.statusText, body.detail);
}

async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url(path), { ...init, headers, credentials: "include" });
}

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<SessionPayload | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(url("/auth/refresh"), { method: "POST", credentials: "include" });
        if (!res.ok) return null;
        const data = (await res.json()) as SessionPayload;
        setAccessToken(data.access_token);
        return data;
      } catch {
        return null;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await rawFetch(path, init);
  if (res.status === 401 && !path.startsWith("/auth/")) {
    const session = await refreshSession();
    if (!session) {
      setAccessToken(null);
      onUnauthenticated();
      throw await toProblem(res);
    }
    res = await rawFetch(path, init);
  }
  if (!res.ok) throw await toProblem(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
