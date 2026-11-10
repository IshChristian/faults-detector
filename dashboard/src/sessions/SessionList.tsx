import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../pages/EmptyState";
import { listSessions, listSites, type Session, type Site } from "./api";
import { ProgressBadge } from "./ProgressBadge";

const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });

export function sessionTitle(s: Pick<Session, "title" | "type" | "starts_at">): string {
  if (s.title) return s.title;
  return `${s.type === "match" ? "Match" : "Training"} · ${dateFormat.format(new Date(s.starts_at))}`;
}

export function SessionList() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [error, setError] = useState(false);
  const canWrite = user?.role !== "viewer";

  useEffect(() => {
    let cancelled = false;
    Promise.all([listSessions(), listSites()])
      .then(([s, st]) => {
        if (cancelled) return;
        setSessions(s.items); // server returns newest first
        setSites(st.items);
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p role="alert">Could not load sessions. Please refresh.</p>;
  if (!sessions) return <p className="muted">Loading sessions…</p>;

  const newLink = canWrite ? (
    <Link to="/sessions/new" className="btn btn-primary btn-link">
      New session
    </Link>
  ) : undefined;

  if (sessions.length === 0) {
    return (
      <EmptyState
        title="No sessions yet."
        body="Upload a training video to analyse your first session."
        action={newLink}
      />
    );
  }

  const siteName = (id: string) => sites.find((s) => s.id === id)?.name ?? "";
  return (
    <>
      {newLink && <div className="toolbar">{newLink}</div>}
      <ul className="session-list">
        {sessions.map((s) => (
          <li key={s.id} className="card session-row">
            <div>
              <Link to={`/sessions/${s.id}`} className="session-title">
                {sessionTitle(s)}
              </Link>
              <div className="muted">{siteName(s.site_id)}</div>
            </div>
            <ProgressBadge status={s.status} progress={s.progress} stage={s.stage} error={s.error} />
          </li>
        ))}
      </ul>
    </>
  );
}
