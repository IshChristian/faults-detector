import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { getSession, processSession, type SessionDetail as Detail } from "./api";
import { ProgressBadge } from "./ProgressBadge";
import { sessionTitle } from "./SessionList";
import { UploadPanel } from "./UploadPanel";

const POLL_MS = 5000;

export function SessionDetail() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const canWrite = user?.role !== "viewer";
  const [session, setSession] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refresh = useCallback(
    async (next?: Detail) => {
      try {
        const s = next ?? (await getSession(id));
        if (alive.current) setSession(s);
      } catch {
        if (alive.current && !next) setError("Could not load this session.");
      }
    },
    [id],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll every 5 s while the server is working; one request at a time, stopped on unmount.
  const status = session?.status;
  useEffect(() => {
    if (status !== "queued" && status !== "processing") return;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async () => {
      await refresh();
      if (!stopped) timer = setTimeout(tick, POLL_MS);
    };
    timer = setTimeout(tick, POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [status, refresh]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      await refresh(await processSession(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start processing.");
    } finally {
      setStarting(false);
    }
  }

  if (error && !session) return <p role="alert">{error}</p>;
  if (!session) return <p className="muted">Loading session…</p>;

  const allUploaded = session.videos.length > 0 && session.videos.every((v) => v.status === "uploaded");
  const canStart = canWrite && session.status === "uploading" && allUploaded && !starting;

  return (
    <>
      <div className="detail-head">
        <h1>{sessionTitle(session)}</h1>
        <ProgressBadge status={session.status} progress={session.progress} stage={session.stage} error={session.error} />
      </div>
      {error && <p role="alert" className="form-error">{error}</p>}
      <p className="muted">Recording tip: phone high up at the halfway line, whole pitch in frame, landscape, 1080p.</p>
      <UploadPanel session={session} canWrite={canWrite} onChange={(s) => void refresh(s)} />
      <div className="detail-actions">
        {canWrite && (
          <Link to={`/sessions/${session.id}/calibrate`} className="btn btn-secondary btn-link">
            Calibrate pitch
          </Link>
        )}
        {canWrite && (
          <button type="button" className="btn btn-primary" disabled={!canStart} onClick={start}>
            Start processing
          </button>
        )}
      </div>
    </>
  );
}
