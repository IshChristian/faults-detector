import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  createPitchPosition,
  createSession,
  listSites,
  listUploadCameras,
  type Camera,
  type SessionType,
  type Site,
} from "./api";

/** "YYYY-MM-DDTHH:mm" wall-clock time of `date` in `timeZone`, for a datetime-local input. */
export function wallTimeInZone(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(date);
  const p = (type: string) => parts.find((x) => x.type === type)?.value ?? "00";
  return `${p("year")}-${p("month")}-${p("day")}T${p("hour")}:${p("minute")}`;
}

function offsetMinutes(at: Date, timeZone: string): number {
  const name = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longOffset" })
    .formatToParts(at)
    .find((x) => x.type === "timeZoneName")?.value;
  const m = name?.match(/GMT([+-])(\d\d):(\d\d)/);
  if (!m) return 0; // plain "GMT" means UTC
  return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]));
}

/** Turn a wall-clock time in `timeZone` ("YYYY-MM-DDTHH:mm") into an ISO string with an explicit offset. */
export function zonedWallTimeToIso(local: string, timeZone: string): string {
  const asUtc = Date.parse(`${local}:00Z`);
  // The offset depends on the instant, so resolve it twice to be right around DST changes.
  let offset = offsetMinutes(new Date(asUtc), timeZone);
  offset = offsetMinutes(new Date(asUtc - offset * 60_000), timeZone);
  const sign = offset < 0 ? "-" : "+";
  const abs = Math.abs(offset);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${local}:00${sign}${hh}:${mm}`;
}

export function NewSessionForm() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState("");
  const [cameras, setCameras] = useState<Camera[] | null>(null);
  const [cameraId, setCameraId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [type, setType] = useState<SessionType>("training");
  const [title, setTitle] = useState("");
  const [squad, setSquad] = useState("");
  const [addingPosition, setAddingPosition] = useState(false);
  const [positionName, setPositionName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const site = sites.find((s) => s.id === siteId);

  useEffect(() => {
    let cancelled = false;
    listSites()
      .then((page) => {
        if (cancelled) return;
        setSites(page.items);
        if (page.items[0]) setSiteId(page.items[0].id);
      })
      .catch(() => !cancelled && setError("Could not load sites."));
    return () => {
      cancelled = true;
    };
  }, []);

  // Default the date/time to "now" in the chosen site's timezone.
  const timezone = site?.timezone;
  useEffect(() => {
    if (timezone) setStartsAt(wallTimeInZone(new Date(), timezone));
  }, [timezone, siteId]);

  useEffect(() => {
    if (!siteId) return;
    let cancelled = false;
    setCameras(null);
    setCameraId("");
    listUploadCameras(siteId)
      .then((page) => {
        if (cancelled) return;
        setCameras(page.items);
      })
      .catch(() => !cancelled && setError("Could not load pitch positions."));
    return () => {
      cancelled = true;
    };
  }, [siteId]);

  if (user?.role === "viewer") return <p role="alert">You do not have permission to create sessions.</p>;

  async function savePosition(e: FormEvent) {
    e.preventDefault();
    if (!positionName.trim()) return;
    setError(null);
    try {
      const cam = await createPitchPosition(siteId, positionName.trim());
      setCameras((prev) => [...(prev ?? []), cam]);
      setCameraId(cam.id);
      setAddingPosition(false);
      setPositionName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the pitch position.");
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!cameraId) {
      setError("Choose a pitch position.");
      return;
    }
    if (!site || !startsAt) return;
    setBusy(true);
    try {
      const created = await createSession({
        site_id: siteId,
        source_id: cameraId,
        type,
        starts_at: zonedWallTimeToIso(startsAt, site.timezone),
        ...(title.trim() && { title: title.trim() }),
        ...(squad.trim() && { squad: squad.trim() }),
      });
      navigate(`/sessions/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the session.");
      setBusy(false);
    }
  }

  const noPositions = cameras !== null && cameras.length === 0;

  return (
    <>
      <h1>New session</h1>
      <form className="card form-grid" onSubmit={submit} noValidate>
        <label className="field">
          Site
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>

        <div className="field">
          <label htmlFor="pitch-position">Pitch position</label>
          <select id="pitch-position" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
            <option value="">Select a pitch position</option>
            {(cameras ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {noPositions && !addingPosition && <span className="muted">This site has no pitch positions yet.</span>}
          {!addingPosition && siteId && (
            <button type="button" className="btn btn-link-button" onClick={() => setAddingPosition(true)}>
              Add pitch position
            </button>
          )}
        </div>

        {addingPosition && (
          <div className="field inline-form">
            <label htmlFor="position-name">Position name</label>
            <input id="position-name" value={positionName} onChange={(e) => setPositionName(e.target.value)} />
            <button type="button" className="btn btn-primary" onClick={savePosition}>
              Save position
            </button>
          </div>
        )}

        <label className="field">
          Date and time{timezone ? ` (${timezone})` : ""}
          <input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
        </label>

        <label className="field">
          Type
          <select value={type} onChange={(e) => setType(e.target.value as SessionType)}>
            <option value="training">Training</option>
            <option value="match">Match</option>
          </select>
        </label>

        <label className="field">
          Title (optional)
          <input value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} />
        </label>

        <label className="field">
          Squad (optional)
          <input value={squad} maxLength={100} onChange={(e) => setSquad(e.target.value)} />
        </label>

        {error && <p role="alert" className="form-error">{error}</p>}
        <div>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Create session
          </button>
        </div>
      </form>
    </>
  );
}
