import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { App } from "../App";
import { API, coach, server, type TestUser } from "../test/server";

function signedInAs(user: TestUser, path: string) {
  server.use(
    http.post(`${API}/auth/refresh`, () =>
      HttpResponse.json({ access_token: "a", refresh_token: "r", token_type: "bearer", user }),
    ),
  );
  window.history.pushState({}, "", path);
  return render(<App />);
}

test("operator sees 'Coach' label in user menu when customer industry is sports", async () => {
  signedInAs(coach, "/sessions");
  const menu = await screen.findByRole("button", { name: /account menu/i });
  expect(menu).toHaveTextContent("Coach");
  expect(menu).not.toHaveTextContent("Operator");
});

test("operator is labelled Operator for non-sports customers, who land on Live Operations", async () => {
  signedInAs({ ...coach, customer_industry: "restaurant" }, "/");
  expect(await screen.findByRole("button", { name: /account menu/i })).toHaveTextContent("Operator");
  expect(window.location.pathname).toBe("/live");
});

test("active nav item has aria-current='page'", async () => {
  signedInAs(coach, "/cameras");
  const nav = await screen.findByRole("navigation", { name: /main/i });
  const active = within(nav).getByRole("link", { name: /cameras & screens/i });
  expect(active).toHaveAttribute("aria-current", "page");
  expect(within(nav).getByRole("link", { name: /fault center/i })).not.toHaveAttribute("aria-current");
});

test("cameras page shows the UI doc empty state", async () => {
  signedInAs(coach, "/cameras");
  expect(await screen.findByText("No cameras connected yet.")).toBeInTheDocument();
  expect(screen.getByText("Add your first camera to begin monitoring.")).toBeInTheDocument();
});

test("unknown route shows not found inside the shell", async () => {
  signedInAs(coach, "/nope");
  expect(await screen.findByRole("heading", { name: /page not found/i })).toBeInTheDocument();
});

test("sign out returns to the login page", async () => {
  signedInAs(coach, "/sessions");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /account menu/i }));
  await user.click(screen.getByRole("menuitem", { name: /sign out/i }));
  expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
});
