import { Upload } from "tus-js-client";
import { apiFetch, getAccessToken } from "../api/client";

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

/**
 * Start (or resume) a resumable tus upload. The Authorization header is set per request from
 * the current in-memory token, so a long upload keeps working across access-token refreshes.
 * Re-selecting the same file resumes the earlier upload via tus's stored fingerprint.
 */
export function uploadFile(sessionId: string, file: File, cb: UploadCallbacks): Upload {
  const upload = new Upload(file, {
    endpoint: "/api/v1/uploads",
    chunkSize: 8 * 1024 * 1024,
    retryDelays: [0, 1000, 3000, 5000, 10000, 20000],
    metadata: { session_id: sessionId, filename: file.name },
    removeFingerprintOnSuccess: true,
    onBeforeRequest(req) {
      const token = getAccessToken();
      if (token) req.setHeader("Authorization", `Bearer ${token}`);
    },
    onProgress: cb.onProgress,
    onError: cb.onError,
    onSuccess: cb.onSuccess,
  });
  void upload.findPreviousUploads().then((previous) => {
    if (previous.length > 0) upload.resumeFromPreviousUpload(previous[0]);
    upload.start();
  });
  return upload;
}
