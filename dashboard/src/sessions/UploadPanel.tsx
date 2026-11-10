import { useEffect, useRef, useState } from "react";
import { removeVideo, setVideoOrder, uploadFile, type SessionDetail, type Video } from "./api";
import { ApiProblem } from "../api/client";

type Props = {
  session: SessionDetail;
  canWrite: boolean;
  onChange: (session?: SessionDetail) => void;
};

type Local = { progress: number; error?: string };

export function UploadPanel({ session, canWrite, onChange }: Props) {
  // In-flight uploads by file name (the server only knows a video once tus creates it).
  const [local, setLocal] = useState<Record<string, Local>>({});
  const [message, setMessage] = useState<string | null>(null);
  const uploads = useRef<Array<{ abort: () => void }>>([]);

  useEffect(() => {
    const running = uploads.current;
    return () => running.forEach((u) => u.abort()); // tus keeps its fingerprint, so re-selecting resumes
  }, []);

  function addFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      setLocal((p) => ({ ...p, [file.name]: { progress: 0 } }));
      const upload = uploadFile(session.id, file, {
        onProgress: (sent, total) =>
          setLocal((p) => ({ ...p, [file.name]: { progress: total ? Math.round((sent / total) * 100) : 0 } })),
        onError: (err) => setLocal((p) => ({ ...p, [file.name]: { progress: p[file.name]?.progress ?? 0, error: err.message } })),
        onSuccess: () => {
          setLocal((p) => {
            const { [file.name]: _done, ...rest } = p;
            return rest;
          });
          onChange();
        },
      });
      uploads.current.push(upload);
    }
  }

  async function move(index: number, delta: -1 | 1) {
    const ids = session.videos.map((v) => v.id);
    [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
    setMessage(null);
    try {
      onChange(await setVideoOrder(session.id, ids));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not reorder the videos.");
    }
  }

  async function remove(video: Video) {
    setMessage(null);
    try {
      await removeVideo(video.id);
      onChange();
    } catch (err) {
      setMessage(
        err instanceof ApiProblem && err.status === 409
          ? "This video is still being written. Wait a moment and try again."
          : "Could not remove the video. Please try again.",
      );
    }
  }

  // Matches the backend DELETE rule: nothing can be removed while the session is queued or processing.
  const canRemove = canWrite && session.status !== "queued" && session.status !== "processing";
  const known = new Set(session.videos.map((v) => v.original_filename));
  const pending = Object.keys(local).filter((name) => !known.has(name));

  return (
    <section className="card upload-panel" aria-label="Videos">
      <h2>Videos</h2>
      {canWrite && (
        <label className="field">
          Add videos
          <input
            type="file"
            accept="video/*"
            multiple
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      )}
      {message && <p role="alert" className="form-error">{message}</p>}
      <ul className="video-list">
        {session.videos.map((v, i) => {
          const name = v.original_filename ?? v.id;
          const l = v.original_filename ? local[v.original_filename] : undefined;
          const pct = v.status === "uploading" ? (l?.progress ?? 0) : 100;
          return (
            <li key={v.id} className="video-row">
              <span className="video-name">{name}</span>
              <span className="muted">{v.status}</span>
              <Bar name={name} value={pct} />
              {v.status === "failed" && <span className="form-error">{v.error ?? l?.error ?? "Upload failed"}</span>}
              {v.status === "uploading" && !l && <span className="muted">Re-select this file to resume</span>}
              {canWrite && (
                <span className="video-actions">
                  <button type="button" className="btn-icon" aria-label={`Move ${name} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                    ↑
                  </button>
                  <button type="button" className="btn-icon" aria-label={`Move ${name} down`} disabled={i === session.videos.length - 1} onClick={() => move(i, 1)}>
                    ↓
                  </button>
                  {canRemove && (
                    <button type="button" className="btn btn-secondary" aria-label={`Remove ${name}`} onClick={() => remove(v)}>
                      Remove
                    </button>
                  )}
                </span>
              )}
            </li>
          );
        })}
        {pending.map((name) => (
          <li key={`local-${name}`} className="video-row">
            <span className="video-name">{name}</span>
            <span className="muted">uploading</span>
            <Bar name={name} value={local[name].progress} />
            {local[name].error && <span className="form-error">{local[name].error}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Bar({ name, value }: { name: string; value: number }) {
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={`${name} upload progress`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div className="progress-fill" style={{ width: `${value}%` }} />
    </div>
  );
}
