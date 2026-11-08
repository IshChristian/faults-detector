import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { App } from "../App";

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

test("unauthenticated user is redirected to /login", async () => {
  renderAt("/live");
  expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/login");
});

test("successful login shows the app shell with all five nav items", async () => {
  renderAt("/login");
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(/email/i), "Coach@Academy.rw");
  await user.type(screen.getByLabelText(/password/i), "Passw0rd!long");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
  const nav = await screen.findByRole("navigation", { name: /main/i });
  for (const label of ["Live Operations", "Fault Center", "Sessions", "Cameras & Screens", "Settings"]) {
    expect(nav).toHaveTextContent(label);
  }
  // sports customer lands on Sessions
  expect(window.location.pathname).toBe("/sessions");
});

test("wrong password shows the problem detail message and stays on /login", async () => {
  renderAt("/login");
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText(/email/i), "coach@academy.rw");
  await user.type(screen.getByLabelText(/password/i), "wrong-password");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  expect(window.location.pathname).toBe("/login");
});
