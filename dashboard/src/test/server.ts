import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const API = "http://localhost:3000/api/v1";

export type TestUser = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  customer_id: string | null;
  customer_industry: string | null;
};

export const coach: TestUser = {
  id: "u-1",
  email: "coach@academy.rw",
  full_name: "Aline Uwase",
  role: "operator",
  customer_id: "c-1",
  customer_industry: "sports",
};

export function problem(status: number, slug: string, title: string, detail?: string) {
  return HttpResponse.json(
    { type: `https://visionguard.ai/errors/${slug}`, title, status, detail },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

/** Default backend: no session yet; one valid account. */
export function authHandlers(user: TestUser = coach, password = "Passw0rd!long") {
  return [
    http.post(`${API}/auth/refresh`, () => problem(401, "invalid-refresh-token", "Session expired")),
    http.post(`${API}/auth/login`, async ({ request }) => {
      const body = (await request.json()) as { email: string; password: string };
      if (body.email.toLowerCase() === user.email && body.password === password) {
        return HttpResponse.json({ access_token: "access-1", refresh_token: "r", token_type: "bearer", user });
      }
      return problem(401, "invalid-credentials", "Invalid email or password");
    }),
    http.post(`${API}/auth/logout`, () => new HttpResponse(null, { status: 204 })),
    http.get(`${API}/auth/me`, () => HttpResponse.json(user)),
  ];
}

export const server = setupServer(...authHandlers());
