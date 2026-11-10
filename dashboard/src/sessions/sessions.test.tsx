import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setAccessToken } from "../api/client";
import { API, coach, problem, server, type TestUser } from "../test/server";
import { uploadFile } from "./api";

type FakeOptions = {
  headers?: Record<string, string>;
  chunkSize: number;
  retryDelays: number[];
  endpoint: string;
  metadata: Record<string, string>;
  removeFingerprintOnSuccess: boolean;
  onBeforeRequest?: (req: { setHeader(name: string, value: string): void }) => void;
  onProgress?: (sent: number, total: number) => void;
  onSuccess?: () => void;
  onError?: (err: Error) => void;
};

const tus = vi.hoisted(() => ({
  uploads: [] as Array<{
    file: File;
    options: FakeOptions;
    started: boolean;
    previous: unknown[];
    resumed: unknown;
    abort: () => void;
  }>,
  previous: [] as unknown[],
}));

vi.mock("tus-js-client", () => {
  class Upload {
    started = false;
    previous: unknown[] = [];
    resumed: unknown = null;
    abort = vi.fn();
    constructor(
      public file: File,
      public options: FakeOptions,
    ) {
      tus.uploads.push(this);
    }
    async findPreviousUploads() {
      this.previous = tus.previous;
      return tus.previous;
    }
    resumeFromPreviousUpload(prev: unknown) {
      this.resumed = prev;
    }
    start() {
      this.started = true;
    }
  }
  return { Upload };
});

afterEach(() => {
  tus.uploads.length = 0;
  tus.previous = [];
  vi.useRealTimers();
  setAccessToken(null);
});

const site = { id: "site-1", name: "Main Pitch", timezone: "Africa/Kigali" };
const camera = { id: "cam-1", site_id: "site-1", name: "Halfway line", mode: "upload", source_type: "phone" };

function page<T>(items: T[]) {
  return HttpResponse.json({ items, next_cursor: null });
}

function sessionRow(over: Record<string, unknown> = {}) {
  return {
    id: "s-1",
    site_id: "site-1",
    source_id: "cam-1",
    type: "training",
    starts_at: "2026-11-02T08:00:00Z",
    title: null,
    squad: null,
    status: "uploading",
    progress: 0,
    stage: null,
    error: null,
    calibration_id: null,
    created_at: "2026-11-02T08:00:00Z",
    updated_at: "2026-11-02T08:00:00Z",
    ...over,
  };
}

function video(id: string, position: number, over: Record<string, unknown> = {}) {
  return { id, position, original_filename: `${id}.mp4`, size_bytes: 100, status: "uploaded", error: null, ...over };
}

function signedInAs(user: TestUser, path: string) {
  server.use(
    http.post(`${API}/auth/refresh`, () =>
      HttpResponse.json({ access_token: "a", refresh_token: "r", token_type: "bearer", user }),
    ),
    http.get(`${API}/sites`, () => page([site])),
  );
  window.history.pushState({}, "", path);
  return render(<App />);
}

test("lists sessions with status badges and progress", async () => {
  server.use(
    http.get(`${API}/sessions`, () =>
      page([
        sessionRow({ id: "s-4", title: "Friday drills", status: "ready" }),
        sessionRow({ id: "s-3", status: "processing", progress: 40, stage: "tracking" }),
        sessionRow({ id: "s-2", status: "failed", error: "No players detected" }),
        sessionRow({ id: "s-1", status: "uploading" }),
      ]),
    ),
  );
  signedInAs(coach, "/sessions");
  expect(await screen.findByText("Friday drills")).toBeInTheDocument();
  expect(screen.getByText("Ready")).toBeInTheDocument();
  expect(screen.getByText(/Processing 40%/)).toHaveTextContent("tracking");
  expect(screen.getByText(/No players detected/)).toBeInTheDocument();
  expect(screen.getByText("Uploading")).toBeInTheDocument();
  expect(screen.getAllByText(/Training · /).length).toBeGreaterThan(0);
  expect(screen.getAllByText("Main Pitch").length).toBe(4);
  const links = screen.getAllByRole("link", { name: /Friday drills|Training/ });
  expect(links[0]).toHaveAttribute("href", "/sessions/s-4");
});

test("shows the empty state when there are no sessions", async () => {
  server.use(http.get(`${API}/sessions`, () => page([])));
  signedInAs(coach, "/sessions");
  expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
  expect(screen.getByText("Upload a training video to analyse your first session.")).toBeInTheDocument();
});

test("new session form requires a pitch position and creates the session", async () => {
  let posted: Record<string, unknown> | null = null;
  server.use(
    http.get(`${API}/cameras`, ({ request }) => {
      const u = new URL(request.url);
      expect(u.searchParams.get("site_id")).toBe("site-1");
      expect(u.searchParams.get("mode")).toBe("upload");
      return page([camera]);
    }),
    http.post(`${API}/sessions`, async ({ request }) => {
      posted = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ ...sessionRow(), videos: [] }, { status: 201 });
    }),
    http.get(`${API}/sessions/s-1`, () => HttpResponse.json({ ...sessionRow(), videos: [] })),
  );
  signedInAs(coach, "/sessions/new");
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "Halfway line" });

  await user.click(screen.getByRole("button", { name: "Create session" }));
  expect(await screen.findByText("Choose a pitch position.")).toBeInTheDocument();
  expect(posted).toBeNull();

  await user.selectOptions(screen.getByLabelText("Pitch position"), "cam-1");
  await user.selectOptions(screen.getByLabelText("Type"), "match");
  await user.type(screen.getByLabelText(/Title/), "Cup semi");
  await user.type(screen.getByLabelText(/Squad/), "U17");
  await user.click(screen.getByRole("button", { name: "Create session" }));

  await waitFor(() => expect(posted).not.toBeNull());
  expect(posted).toMatchObject({ site_id: "site-1", source_id: "cam-1", type: "match", title: "Cup semi", squad: "U17" });
  // Africa/Kigali is UTC+2, no DST: the offset must be explicit in the ISO string.
  expect(String(posted!.starts_at)).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:00\+02:00$/);
  expect(await screen.findByRole("heading", { name: /Upload videos|Cup semi|Training|Match/ })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/sessions/s-1");
});

test("offers to add a pitch position when the site has none", async () => {
  let created: Record<string, unknown> | null = null;
  let cameras: unknown[] = [];
  server.use(
    http.get(`${API}/cameras`, () => page(cameras)),
    http.post(`${API}/cameras`, async ({ request }) => {
      created = (await request.json()) as Record<string, unknown>;
      cameras = [camera];
      return HttpResponse.json(camera, { status: 201 });
    }),
  );
  signedInAs(coach, "/sessions/new");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Add pitch position" }));
  await user.type(screen.getByLabelText("Position name"), "Halfway line");
  await user.click(screen.getByRole("button", { name: "Save position" }));
  await waitFor(() =>
    expect(created).toEqual({ site_id: "site-1", name: "Halfway line", mode: "upload", source_type: "phone" }),
  );
  expect(await screen.findByRole("option", { name: "Halfway line" })).toBeInTheDocument();
  expect(screen.getByLabelText("Pitch position")).toHaveValue("cam-1");
});

function detailHandlers(state: { session: Record<string, unknown> }) {
  server.use(http.get(`${API}/sessions/s-1`, () => HttpResponse.json(state.session)));
}

test("uploading two files shows per-file progress and enables Start processing when done", async () => {
  const state = { session: { ...sessionRow(), videos: [] as unknown[] } };
  detailHandlers(state);
  let processed = false;
  server.use(
    http.post(`${API}/sessions/s-1/process`, () => {
      processed = true;
      return HttpResponse.json({ ...state.session, status: "queued" }, { status: 202 });
    }),
  );
  signedInAs(coach, "/sessions/s-1");
  const user = userEvent.setup();
  expect(await screen.findByText(/Recording tip: phone high up at the halfway line/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Calibrate pitch" })).toHaveAttribute("href", "/sessions/s-1/calibrate");
  expect(screen.getByRole("button", { name: "Start processing" })).toBeDisabled();

  const files = [
    new File(["a"], "first.mp4", { type: "video/mp4" }),
    new File(["b"], "second.mp4", { type: "video/mp4" }),
  ];
  const input = screen.getByLabelText("Add videos");
  expect(input).toHaveAttribute("accept", "video/*");
  expect(input).toHaveAttribute("multiple");
  await user.upload(input, files);
  await waitFor(() => expect(tus.uploads.length).toBe(2));
  await waitFor(() => expect(tus.uploads.every((u) => u.started)).toBe(true));
  expect(tus.uploads[0].options).toMatchObject({
    endpoint: "/api/v1/uploads",
    chunkSize: 8 * 1024 * 1024,
    retryDelays: [0, 1000, 3000, 5000, 10000, 20000],
    metadata: { session_id: "s-1", filename: "first.mp4" },
    removeFingerprintOnSuccess: true,
  });

  act(() => {
    tus.uploads[0].options.onProgress?.(50, 100);
    tus.uploads[1].options.onProgress?.(25, 100);
  });
  expect(screen.getByRole("progressbar", { name: "first.mp4 upload progress" })).toHaveAttribute("aria-valuenow", "50");
  expect(screen.getByRole("progressbar", { name: "second.mp4 upload progress" })).toHaveAttribute("aria-valuenow", "25");
  expect(screen.getByRole("button", { name: "Start processing" })).toBeDisabled();

  state.session = { ...sessionRow(), videos: [video("first", 0), video("second", 1)] };
  act(() => {
    tus.uploads[0].options.onSuccess?.();
    tus.uploads[1].options.onSuccess?.();
  });
  const start = screen.getByRole("button", { name: "Start processing" });
  await waitFor(() => expect(start).toBeEnabled());
  await user.click(start);
  await waitFor(() => expect(processed).toBe(true));
});

test("reordering videos calls the video-order endpoint", async () => {
  const state = { session: { ...sessionRow(), videos: [video("a", 0), video("b", 1)] } };
  detailHandlers(state);
  let order: unknown = null;
  server.use(
    http.put(`${API}/sessions/s-1/video-order`, async ({ request }) => {
      order = await request.json();
      return HttpResponse.json({ ...state.session, videos: [video("b", 0), video("a", 1)] });
    }),
  );
  signedInAs(coach, "/sessions/s-1");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Move b.mp4 up" }));
  await waitFor(() => expect(order).toEqual({ video_ids: ["b", "a"] }));
  expect(screen.getByRole("button", { name: "Move a.mp4 down" })).toBeDisabled();
});

test("a failed video shows the server message and a Remove button", async () => {
  const state = {
    session: {
      ...sessionRow(),
      videos: [video("bad", 0, { status: "failed", error: "Unsupported codec" }), video("ok", 1)],
    },
  };
  detailHandlers(state);
  let attempts = 0;
  server.use(
    http.delete(`${API}/uploads/bad`, () => {
      attempts += 1;
      if (attempts === 1) return problem(409, "upload-busy", "Upload busy");
      state.session = { ...sessionRow(), videos: [video("ok", 0)] };
      return new HttpResponse(null, { status: 204 });
    }),
  );
  signedInAs(coach, "/sessions/s-1");
  const user = userEvent.setup();
  expect(await screen.findByText("Unsupported codec")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /^Remove/ })).toHaveLength(1);

  await user.click(screen.getByRole("button", { name: "Remove bad.mp4" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/try again/i);
  await user.click(screen.getByRole("button", { name: "Remove bad.mp4" }));
  await waitFor(() => expect(screen.queryByText("Unsupported codec")).not.toBeInTheDocument());
  expect(screen.getByText("ok.mp4")).toBeInTheDocument();
});

test("polls while processing and stops when ready", async () => {
  let calls = 0;
  server.use(
    http.get(`${API}/sessions/s-1`, () => {
      calls += 1;
      const ready = calls >= 3;
      return HttpResponse.json({
        ...sessionRow({ status: ready ? "ready" : "processing", progress: calls * 30, stage: "tracking" }),
        videos: [video("a", 0)],
      });
    }),
  );
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  signedInAs(coach, "/sessions/s-1");
  await vi.waitFor(() => expect(screen.getByText(/Processing 30%/)).toBeInTheDocument());
  expect(calls).toBe(1);

  await act(() => vi.advanceTimersByTimeAsync(4900));
  expect(calls).toBe(1);
  await act(() => vi.advanceTimersByTimeAsync(200));
  await vi.waitFor(() => expect(screen.getByText(/Processing 60%/)).toBeInTheDocument());
  expect(calls).toBe(2);
  await act(() => vi.advanceTimersByTimeAsync(5000));
  await vi.waitFor(() => expect(screen.getByText("Ready")).toBeInTheDocument());
  expect(calls).toBe(3);

  await act(() => vi.advanceTimersByTimeAsync(30000));
  expect(calls).toBe(3);
});

test("polling stops when the page unmounts", async () => {
  let calls = 0;
  server.use(
    http.get(`${API}/sessions/s-1`, () => {
      calls += 1;
      return HttpResponse.json({ ...sessionRow({ status: "processing", progress: 10 }), videos: [video("a", 0)] });
    }),
  );
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  const view = signedInAs(coach, "/sessions/s-1");
  await vi.waitFor(() => expect(screen.getByText(/Processing 10%/)).toBeInTheDocument());
  view.unmount();
  await act(() => vi.advanceTimersByTimeAsync(20000));
  expect(calls).toBe(1);
});

test("viewer sees no upload or process controls", async () => {
  const state = { session: { ...sessionRow(), videos: [video("a", 0, { status: "failed", error: "bad" })] } };
  detailHandlers(state);
  signedInAs({ ...coach, role: "viewer" }, "/sessions/s-1");
  expect(await screen.findByText("a.mp4")).toBeInTheDocument();
  expect(screen.queryByLabelText("Add videos")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start processing" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Move/ })).not.toBeInTheDocument();
});

test("viewer sees no New session button", async () => {
  server.use(http.get(`${API}/sessions`, () => page([])));
  signedInAs({ ...coach, role: "viewer" }, "/sessions");
  await screen.findByText("No sessions yet.");
  expect(screen.queryByRole("link", { name: "New session" })).not.toBeInTheDocument();
});

test("uploadFile resumes a previous upload and sends the current token on every request", async () => {
  tus.previous = [{ uploadUrl: "/api/v1/uploads/abc" }];
  setAccessToken("token-1");
  uploadFile("s-1", new File(["x"], "clip.mp4", { type: "video/mp4" }), {
    onProgress: () => {},
    onError: () => {},
    onSuccess: () => {},
  });
  await waitFor(() => expect(tus.uploads[0]?.started).toBe(true));
  expect(tus.uploads[0].resumed).toBe(tus.previous[0]);

  const seen: string[] = [];
  const req = { setHeader: (n: string, v: string) => seen.push(`${n}=${v}`) };
  tus.uploads[0].options.onBeforeRequest?.(req);
  setAccessToken("token-2");
  tus.uploads[0].options.onBeforeRequest?.(req);
  expect(seen).toEqual(["Authorization=Bearer token-1", "Authorization=Bearer token-2"]);
});

