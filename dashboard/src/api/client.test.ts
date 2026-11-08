import { http, HttpResponse, delay } from "msw";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { API, problem, server } from "../test/server";
import { ApiProblem, apiFetch, configureClient, setAccessToken } from "./client";

describe("apiFetch", () => {
  beforeEach(() => {
    setAccessToken("old-token");
    configureClient({ onUnauthenticated: () => {} });
  });

  test("401 triggers exactly one refresh for two concurrent requests, then both retry", async () => {
    let refreshCalls = 0;
    server.use(
      http.get(`${API}/things/:id`, ({ request, params }) =>
        request.headers.get("Authorization") === "Bearer new-token"
          ? HttpResponse.json({ id: params.id })
          : problem(401, "invalid-token", "Invalid or expired token"),
      ),
      http.post(`${API}/auth/refresh`, async () => {
        refreshCalls += 1;
        await delay(20);
        return HttpResponse.json({ access_token: "new-token", refresh_token: "r2", token_type: "bearer", user: {} });
      }),
    );
    const [a, b] = await Promise.all([apiFetch<{ id: string }>("/things/a"), apiFetch<{ id: string }>("/things/b")]);
    expect(a.id).toBe("a");
    expect(b.id).toBe("b");
    expect(refreshCalls).toBe(1);
  });

  test("failed refresh calls onUnauthenticated", async () => {
    const onUnauthenticated = vi.fn();
    configureClient({ onUnauthenticated });
    server.use(http.get(`${API}/things`, () => problem(401, "invalid-token", "Invalid or expired token")));
    await expect(apiFetch("/things")).rejects.toBeInstanceOf(ApiProblem);
    expect(onUnauthenticated).toHaveBeenCalledOnce();
  });

  test("problem+json errors are thrown as ApiProblem with type and detail", async () => {
    server.use(http.get(`${API}/sites/x`, () => problem(404, "not-found", "Not found", "site not found")));
    const err = (await apiFetch("/sites/x").catch((e: unknown) => e)) as ApiProblem;
    expect(err).toBeInstanceOf(ApiProblem);
    expect(err.status).toBe(404);
    expect(err.type).toBe("https://visionguard.ai/errors/not-found");
    expect(err.detail).toBe("site not found");
  });

  test("sends credentials and the bearer token", async () => {
    let seen: string | null = null;
    server.use(
      http.get(`${API}/me-ish`, ({ request }) => {
        seen = request.headers.get("Authorization");
        return HttpResponse.json({});
      }),
    );
    await apiFetch("/me-ish");
    expect(seen).toBe("Bearer old-token");
  });
});
