import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { getSession, type SessionDetail } from "./api";
import {
  DEFAULT_LANDMARKS,
  LANDMARK_KEYS,
  LANDMARK_LABELS,
  getFrame,
  listCalibrations,
  saveCalibration,
  toRelative,
  type Calibration,
  type Frame,
  type Landmark,
  type Point,
} from "./calibration";

const NEEDED = 4;
const MAX_SECONDS = 60;
const STEP_SECONDS = 5;

const message = (err: unknown, fallback: string) => (err instanceof Error && err.message ? err.message : fallback);

export function CalibrationPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const canWrite = user?.role !== "viewer";
  const imgRef = useRef<HTMLImageElement>(null);
  const dragging = useRef<number | null>(null);

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Calibration | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [landmarks, setLandmarks] = useState<Landmark[]>(DEFAULT_LANDMARKS);
  const [lengthM, setLengthM] = useState("100");
  const [widthM, setWidthM] = useState("64");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const videoId = session?.videos[0]?.id;
  const cameraId = session?.source_id;

  useEffect(() => {
    let live = true;
    getSession(id)
      .then((s) => live && setSession(s))
      .catch(() => live && setLoadError("Could not load this session."));
    return () => {
      live = false;
    };
  }, [id]);

  useEffect(() => {
    if (!cameraId) return;
    let live = true;
    listCalibrations(cameraId)
      .then((p) => live && setPrevious(p.items[0] ?? null))
      .catch(() => undefined); // reuse is optional; the page works without it
    return () => {
      live = false;
    };
  }, [cameraId]);

  // Re-fetch the frame when the slider moves; the clicked points are kept.
  useEffect(() => {
    if (!videoId) return;
    let live = true;
    setFrameError(null);
    getFrame(id, videoId, seconds * 1000)
      .then((f) => live && setFrame(f))
      .catch((err) => live && setFrameError(message(err, "Could not load a frame.")));
    return () => {
      live = false;
    };
  }, [id, videoId, seconds]);

  const undo = () => setPoints((p) => p.slice(0, -1));
  const reset = () => setPoints([]);

  useEffect(() => {
    if (!canWrite) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Backspace") return;
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA")) return;
      e.preventDefault();
      setPoints((p) => p.slice(0, -1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canWrite]);

  function relativeFromEvent(clientX: number, clientY: number): Point | null {
    const img = imgRef.current;
    return img ? toRelative(clientX, clientY, img.getBoundingClientRect()) : null;
  }

  function addPoint(e: React.MouseEvent<HTMLImageElement>) {
    if (!canWrite || points.length >= NEEDED) return;
    const p = relativeFromEvent(e.clientX, e.clientY);
    if (p) setPoints((prev) => (prev.length < NEEDED ? [...prev, p] : prev));
  }

  function startDrag(e: ReactPointerEvent<HTMLButtonElement>, index: number) {
    dragging.current = index;
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function moveDrag(e: ReactPointerEvent<HTMLButtonElement>) {
    const index = dragging.current;
    if (index === null) return;
    const p = relativeFromEvent(e.clientX, e.clientY);
    if (p) setPoints((prev) => prev.map((old, i) => (i === index ? p : old)));
  }

  function endDrag() {
    dragging.current = null;
  }

  async function submit(body: Parameters<typeof saveCalibration>[1]) {
    setSaving(true);
    setSaveError(null);
    setSaved(null);
    try {
      const out = await saveCalibration(id, body);
      setSaved(
        out.session.status === "ready"
          ? "Calibration saved. Metrics will update in a few minutes."
          : "Calibration saved.",
      );
    } catch (err) {
      setSaveError(message(err, "Could not save the calibration."));
    } finally {
      setSaving(false);
    }
  }

  const length = Number(lengthM);
  const width = Number(widthM);
  const sizeOk = length >= 10 && length <= 200 && width >= 10 && width <= 200;
  const distinct = new Set(landmarks.slice(0, points.length)).size === points.length;
  const ready = points.length === NEEDED && sizeOk && distinct && !saving;

  function save() {
    if (!ready) return;
    void submit({
      image_points: points,
      landmarks: landmarks.slice(0, NEEDED),
      pitch_length_m: length,
      pitch_width_m: width,
    });
  }

  if (loadError) return <p role="alert">{loadError}</p>;
  if (!session) return <p className="muted">Loading session…</p>;

  return (
    <>
      <div className="detail-head">
        <h1>Calibrate pitch</h1>
        <Link to={`/sessions/${session.id}`} className="btn btn-secondary btn-link">
          Back to session
        </Link>
      </div>
      <p className="muted">
        {canWrite
          ? "Click four known points on the pitch, such as the corners. Drag a marker to adjust it."
          : "Calibration frame (read-only)."}
      </p>

      {!videoId && <p className="muted">Upload a video first, then calibrate the pitch.</p>}
      {frameError && <p role="alert" className="form-error">{frameError}</p>}

      {videoId && (
        <label className="field calib-slider">
          <span>
            Frame time: <span className="num">{seconds}</span> s
          </span>
          <input
            type="range"
            min={0}
            max={MAX_SECONDS}
            step={STEP_SECONDS}
            value={seconds}
            onChange={(e) => setSeconds(Number(e.target.value))}
          />
        </label>
      )}

      {frame && (
        <div className="calib-stage">
          <img ref={imgRef} src={frame.url} alt="Pitch frame" draggable={false} onClick={addPoint} />
          {canWrite &&
            points.map(([x, y], i) => (
              <button
                key={i}
                type="button"
                className="calib-marker"
                aria-label={`Point ${i + 1}`}
                style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
                onClick={(e) => e.stopPropagation()}
                onPointerDown={(e) => startDrag(e, i)}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              >
                {i + 1}
              </button>
            ))}
        </div>
      )}

      {canWrite && (
        <div className="card calib-panel">
          <p className="muted" aria-live="polite">
            Click {NEEDED} points on the pitch ({points.length} of {NEEDED}).
          </p>
          <div role="group" aria-label="Calibration points" className="calib-points">
            {points.map((_, i) => (
              <label key={i} className="field">
                <span>Point {i + 1}</span>
                <select
                  aria-label={`Point ${i + 1} landmark`}
                  value={landmarks[i]}
                  onChange={(e) =>
                    setLandmarks((prev) => prev.map((l, j) => (j === i ? (e.target.value as Landmark) : l)))
                  }
                >
                  {LANDMARK_KEYS.map((k) => (
                    <option key={k} value={k}>
                      {LANDMARK_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          {!distinct && <p className="form-error">Each point needs a different landmark.</p>}
          <div className="calib-size">
            <label className="field">
              <span>Pitch length (m)</span>
              <input type="number" min={10} max={200} value={lengthM} onChange={(e) => setLengthM(e.target.value)} />
            </label>
            <label className="field">
              <span>Pitch width (m)</span>
              <input type="number" min={10} max={200} value={widthM} onChange={(e) => setWidthM(e.target.value)} />
            </label>
          </div>
          {!sizeOk && <p className="form-error">Pitch length and width must be between 10 and 200 m.</p>}
          {saveError && <p role="alert" className="form-error">{saveError}</p>}
          {saved && <p role="status" className="calib-saved">{saved}</p>}
          <div className="detail-actions">
            <button type="button" className="btn btn-secondary" onClick={undo} disabled={points.length === 0}>
              Undo
            </button>
            <button type="button" className="btn btn-secondary" onClick={reset} disabled={points.length === 0}>
              Reset
            </button>
            <button type="button" className="btn btn-primary" onClick={save} disabled={!ready}>
              Save calibration
            </button>
            {previous && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving}
                onClick={() => void submit({ reuse_calibration_id: previous.id })}
              >
                Use previous calibration ({new Date(previous.created_at).toLocaleDateString()})
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
