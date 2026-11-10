import { Upload } from "tus-js-client";
import { apiFetch, getAccessToken, refreshSession } from "../api/client";

export type Page<T> = { items: T[]; next_cursor: string | null };

export type SessionType = "training" | "match";
export type SessionStatus = "uploading" | "queued" | "processing" | "ready" | "failed";
export type VideoStatus = "uploading" | "uploaded" | "processed" | "failed";

export type Site = { id: string; name: string; timezone: string };
export type Camera = { id: string; site_id: string; name: string; mode: string; source_type: string };

export type Video = {
  id: string;
  position: number;
  original_filename: string | null;
  size_bytes: number;
  status: VideoStatus;
  error: string | null;
};

export type Session = {
  id: string;
  site_id: string;
  source_id: string;
  type: SessionType;
  starts_at: string;
  title: string | null;
  squad: string | null;
  status: SessionStatus;
  progress: number;
  stage: string | null;
  error: string | null;
  calibration_id: string | null;
  created_at: string;
};

export type SessionDetail = Session & { videos: Video[] };

export type NewSession = {
  site_id: string;
  source_id: string;
  type: SessionType;
  starts_at: string;
  title?: string;
  squad?: string;
};

const json = (body: unknown) => ({ body: JSON.stringify(body) });

export const listSessions = () => apiFetch<Page<Session>>("/sessions");
export const getSession = (id: string) => apiFetch<SessionDetail>(`/sessions/${id}`);
export const createSession = (body: NewSession) =>
  apiFetch<SessionDetail>("/sessions", { method: "POST", ...json(body) });
export const processSession = (id: string) => apiFetch<SessionDetail>(`/sessions/${id}/process`, { method: "POST" });
export const setVideoOrder = (id: string, videoIds: string[]) =>
  apiFetch<SessionDetail>(`/sessions/${id}/video-order`, { method: "PUT", ...json({ video_ids: videoIds }) });
export const removeVideo = (videoId: string) => apiFetch<void>(`/uploads/${videoId}`, { method: "DELETE" });

export const listSites = () => apiFetch<Page<Site>>("/sites");
export const listUploadCameras = (siteId: string) =>
  apiFetch<Page<Camera>>(`/cameras?site_id=${encodeURIComponent(siteId)}&mode=upload`);
export const createPitchPosition = (siteId: string, name: string) =>
  apiFetch<Camera>("/cameras", {
    method: "POST",
    ...json({ site_id: siteId, name, mode: "upload", source_type: "phone" }),
  });

export type UploadCallbacks = {
  onProgress: (bytesSent: number, bytesTotal: number) => void;
  onError: (error: Error) => void;
  onSuccess: () => void;
};

const REFRESH_MARGIN_S = 60;
export const SIGN_IN_EXPIRED = "Your sign-in expired. Sign in again and re-select the file to resume.";

/** True when there is no token, or its JWT `exp` is within the refresh margin. Undecodable tokens count as valid. */
function needsRefresh(token: string | null): boolean {
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.exp === "number" && payload.exp - Date.now() / 1000 < REFRESH_MARGIN_S;
  } catch {
    return false;
  }
}

/**
 * Start (or resume) a resumable tus upload. The Authorization header is set per request from
 * the current in-memory token, so a long upload keeps working across access-token refreshes.
 * Re-selecting the same file in the same session resumes the earlier upload via tus's stored fingerprint;
 * the fingerprint includes the session, so the same file in another session starts a new upload.
 */
export function uploadFile(sessionId: string, file: File, cb: UploadCallbacks): Upload {
  let signedOut = false;
  const upload: Upload = new Upload(file, {
    endpoint: "/api/v1/uploads",
    chunkSize: 8 * 1024 * 1024,
    retryDelays: [0, 1000, 3000, 5000, 10000, 20000],
    metadata: { session_id: sessionId, filename: file.name },
    removeFingerprintOnSuccess: true,
    fingerprint: async (f) => {
      const file = f as File;
      return ["vg", sessionId, file.name, file.type, file.size, file.lastModified].join("-");
    },
    async onBeforeRequest(req) {
      // The access token lives ~15 min; long uploads must refresh it (concurrent refreshes are shared).
      if (needsRefresh(getAccessToken()) && !(await refreshSession())) {
        signedOut = true;
        void upload.abort();
        cb.onError(new Error(SIGN_IN_EXPIRED));
        throw new Error(SIGN_IN_EXPIRED);
      }
      const token = getAccessToken();
      if (token) req.setHeader("Authorization", `Bearer ${token}`);
    },
    onShouldRetry(err) {
      if (signedOut) return false;
      const status = err.originalResponse ? err.originalResponse.getStatus() : 0;
      if (status === 401) return true; // the token expired mid-request; onBeforeRequest refreshes it
      return (status < 400 || status >= 500 || status === 409 || status === 423) && navigator.onLine;
    },
    onProgress: cb.onProgress,
    onError: (err) => {
      if (!signedOut) cb.onError(err);
    },
    onSuccess: cb.onSuccess,
  });
  void upload
    .findPreviousUploads()
    .then((previous) => {
      if (previous.length > 0) upload.resumeFromPreviousUpload(previous[0]);
    })
    .catch(() => {}) // no stored uploads to resume (e.g. storage blocked): start a fresh one
    .then(() => upload.start());
  return upload;
}
