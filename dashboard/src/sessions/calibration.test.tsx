import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setAccessToken } from "../api/client";
import { API, coach, problem, server, type TestUser } from "../test/server";
import { LANDMARK_LABELS, toRelative } from "./calibration";

const RECT = { left: 10, top: 20, width: 200, height: 100 };

beforeEach(() => {
  // jsdom has no PointerEvent, so pointer events would lose clientX/clientY.
  if (!("PointerEvent" in window)) {
    class PointerEventShim extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    vi.stubGlobal("PointerEvent", PointerEventShim);
  }
  vi.spyOn(HTMLImageElement.prototype, "getBoundingClientRect").mockReturnValue({
    ...RECT,
    right: RECT.left + RECT.width,
    bottom: RECT.top + RECT.height,
    x: RECT.left,
    y: RECT.top,
    toJSON: () => ({}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAccessToken(null);
});

const sessionDetail = (over: Record<string, unknown> = {}) => ({
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
  videos: [
    { id: "v-1", position: 0, original_filename: "a.mp4", size_bytes: 1, status: "uploaded", error: null },
  ],
  ...over,
});

const previous = {
  id: "cal-0",
  camera_id: "cam-1",
  image_points: [],
  pitch_points: [],
  pitch_length_m: 100,
  pitch_width_m: 64,
  created_by: null,
  created_at: "2026-10-30T09:00:00+00:00",
};

function setup(opts: { user?: TestUser; session?: Record<string, unknown>; calibrations?: unknown[] } = {}) {
  const user = opts.user ?? coach;
  const frameRequests: string[] = [];
  server.use(
    http.post(`${API}/auth/refresh`, () =>
      HttpResponse.json({ access_token: "a", refresh_token: "r", token_type: "bearer", user }),
    ),
    http.get(`${API}/sessions/s-1`, () => HttpResponse.json(sessionDetail(opts.session))),
    http.get(`${API}/sessions/s-1/videos/v-1/frame`, ({ request }) => {
      frameRequests.push(new URL(request.url).searchParams.get("t_ms") ?? "");
      return HttpResponse.json({ url: "/media/frame.jpg", width: 1920, height: 1080 });
    }),
    http.get(`${API}/cameras/cam-1/calibrations`, () =>
      HttpResponse.json({ items: opts.calibrations ?? [], next_cursor: null }),
    ),
  );
  window.history.pushState({}, "", "/sessions/s-1/calibrate");
  render(<App />);
  return { frameRequests };
}

async function clickPoints(points: Array<[number, number]>) {
  const img = await screen.findByAltText("Pitch frame");
  for (const [x, y] of points) fireEvent.click(img, { clientX: x, clientY: y });
}

// With RECT: client (110,70) -> [0.5, 0.5]; (10,20) -> [0,0]; (210,120) -> [1,1]; (110,20) -> [0.5,0]
const FOUR: Array<[number, number]> = [
  [20, 30],
  [200, 30],
  [190, 110],
  [30, 110],
];

test("clicking four points and saving posts relative coordinates and landmarks", async () => {
  let body: Record<string, unknown> | null = null;
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(
        { calibration: previous, session: sessionDetail({ status: "ready" }) },
        { status: 201 },
      );
    }),
  );
  setup();
  const user = userEvent.setup();
  await clickPoints(FOUR);
  await user.click(screen.getByRole("button", { name: "Save calibration" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect(body).toEqual({
    image_points: [
      [0.05, 0.1],
      [0.95, 0.1],
      [0.9, 0.9],
      [0.1, 0.9],
    ],
    landmarks: ["corner_near_left", "corner_near_right", "corner_far_right", "corner_far_left"],
    pitch_length_m: 100,
    pitch_width_m: 64,
  });
  expect(await screen.findByText("Calibration saved. Metrics will update in a few minutes.")).toBeInTheDocument();
});

test("shows a plain saved message when the session is not ready", async () => {
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, () =>
      HttpResponse.json({ calibration: previous, session: sessionDetail() }, { status: 201 }),
    ),
  );
  setup();
  await clickPoints(FOUR);
  await userEvent.setup().click(screen.getByRole("button", { name: "Save calibration" }));
  expect(await screen.findByText("Calibration saved.")).toBeInTheDocument();
});

test("server 422 detail is shown inline", async () => {
  const msg = "The four points are nearly in a line. Pick points that are spread out.";
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, () => problem(422, "invalid-calibration", "Invalid calibration", msg)),
  );
  setup();
  await clickPoints(FOUR);
  await userEvent.setup().click(screen.getByRole("button", { name: "Save calibration" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(msg);
});

test("use previous calibration posts reuse_calibration_id", async () => {
  let body: unknown = null;
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ calibration: previous, session: sessionDetail() }, { status: 201 });
    }),
  );
  setup({ calibrations: [previous] });
  const btn = await screen.findByRole("button", { name: /Use previous calibration \(/ });
  await userEvent.setup().click(btn);
  await waitFor(() => expect(body).toEqual({ reuse_calibration_id: "cal-0" }));
  expect(await screen.findByText("Calibration saved.")).toBeInTheDocument();
});

test("cannot save with fewer than four points", async () => {
  setup();
  await clickPoints(FOUR.slice(0, 3));
  expect(screen.getByRole("button", { name: "Save calibration" })).toBeDisabled();
  expect(screen.getByText("Click 4 points on the pitch (3 of 4).")).toBeInTheDocument();
});

test("toRelative clamps to the image", () => {
  const rect = { left: 10, top: 20, width: 200, height: 100 };
  expect(toRelative(110, 70, rect)).toEqual([0.5, 0.5]);
  expect(toRelative(-50, 500, rect)).toEqual([0, 1]);
  expect(toRelative(999, -5, rect)).toEqual([1, 0]);
});

test("landmark labels cover the nine backend landmarks", () => {
  expect(Object.keys(LANDMARK_LABELS)).toEqual([
    "corner_near_left",
    "corner_near_right",
    "corner_far_right",
    "corner_far_left",
    "halfway_near",
    "halfway_far",
    "centre_spot",
    "penalty_spot_left",
    "penalty_spot_right",
  ]);
  expect(LANDMARK_LABELS.halfway_near).toBe("Halfway line (near)");
});

test("Backspace undoes the last point, Reset clears, landmark can be changed", async () => {
  let body: Record<string, unknown> | null = null;
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ calibration: previous, session: sessionDetail() }, { status: 201 });
    }),
  );
  setup();
  const user = userEvent.setup();
  await clickPoints(FOUR);
  await user.keyboard("{Backspace}");
  expect(screen.getByText("Click 4 points on the pitch (3 of 4).")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Undo" }));
  expect(screen.getByText("Click 4 points on the pitch (2 of 4).")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reset" }));
  expect(screen.getByText("Click 4 points on the pitch (0 of 4).")).toBeInTheDocument();

  const img = screen.getByAltText("Pitch frame");
  for (const [x, y] of FOUR) fireEvent.click(img, { clientX: x, clientY: y });
  await user.selectOptions(screen.getByLabelText("Point 4 landmark"), "centre_spot");
  await user.click(screen.getByRole("button", { name: "Save calibration" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect(body!.landmarks).toEqual(["corner_near_left", "corner_near_right", "corner_far_right", "centre_spot"]);
});

test("a marker can be dragged and stays inside the image", async () => {
  let body: Record<string, unknown> | null = null;
  server.use(
    http.post(`${API}/sessions/s-1/calibration`, async ({ request }) => {
      body = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ calibration: previous, session: sessionDetail() }, { status: 201 });
    }),
  );
  setup();
  await clickPoints(FOUR);
  const marker = screen.getByRole("button", { name: "Point 1" });
  fireEvent.pointerDown(marker, { pointerId: 1, clientX: 20, clientY: 30 });
  fireEvent.pointerMove(marker, { pointerId: 1, clientX: -500, clientY: 70 });
  fireEvent.pointerUp(marker, { pointerId: 1 });
  await userEvent.setup().click(screen.getByRole("button", { name: "Save calibration" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect((body!.image_points as number[][])[0]).toEqual([0, 0.5]);
});

test("changing the time slider refetches the frame and keeps the points", async () => {
  const { frameRequests } = setup();
  await clickPoints(FOUR.slice(0, 2));
  await waitFor(() => expect(frameRequests).toEqual(["0"]));
  fireEvent.change(screen.getByLabelText(/Frame time/), { target: { value: "15" } });
  await waitFor(() => expect(frameRequests).toEqual(["0", "15000"]));
  expect(screen.getByText("Click 4 points on the pitch (2 of 4).")).toBeInTheDocument();
});

test("shows the server message when the frame cannot be read", async () => {
  setup();
  server.use(
    http.get(`${API}/sessions/s-1/videos/v-1/frame`, () =>
      problem(409, "conflict", "Conflict", "The video has not finished uploading"),
    ),
  );
  expect(await screen.findByText("The video has not finished uploading")).toBeInTheDocument();
});

test("a viewer sees the frame but has no Save button", async () => {
  setup({ user: { ...coach, role: "viewer" } });
  const img = await screen.findByAltText("Pitch frame");
  fireEvent.click(img, { clientX: 50, clientY: 50 });
  expect(screen.queryByRole("button", { name: "Save calibration" })).not.toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Calibration points" })).not.toBeInTheDocument();
  expect(within(document.body).queryByRole("button", { name: "Point 1" })).not.toBeInTheDocument();
});
