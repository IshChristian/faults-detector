import { apiFetch } from "../api/client";
import type { Page, SessionDetail } from "./api";

/** Same keys as backend `app.analysis.pitch.LANDMARKS`. */
export const LANDMARK_LABELS = {
  corner_near_left: "Near-left corner",
  corner_near_right: "Near-right corner",
  corner_far_right: "Far-right corner",
  corner_far_left: "Far-left corner",
  halfway_near: "Halfway line (near)",
  halfway_far: "Halfway line (far)",
  centre_spot: "Centre spot",
  penalty_spot_left: "Left penalty spot",
  penalty_spot_right: "Right penalty spot",
} as const;

export type Landmark = keyof typeof LANDMARK_LABELS;
export const LANDMARK_KEYS = Object.keys(LANDMARK_LABELS) as Landmark[];
/** Default landmarks for the four clicks, in order. */
export const DEFAULT_LANDMARKS: Landmark[] = LANDMARK_KEYS.slice(0, 4);

export type Point = [number, number];
export type Rect = { left: number; top: number; width: number; height: number };

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Client coordinates to relative 0-1 image coordinates (origin top-left), clamped to the image. */
export function toRelative(clientX: number, clientY: number, rect: Rect): Point {
  if (rect.width <= 0 || rect.height <= 0) return [0, 0];
  return [clamp01((clientX - rect.left) / rect.width), clamp01((clientY - rect.top) / rect.height)];
}

export type Frame = { url: string; width: number; height: number };

export type Calibration = {
  id: string;
  camera_id: string;
  image_points: number[][];
  pitch_points: number[][];
  pitch_length_m: number;
  pitch_width_m: number;
  created_by: string | null;
  created_at: string;
};

export type CalibrationSaved = { calibration: Calibration; session: SessionDetail };

export type CalibrationBody =
  | { image_points: Point[]; landmarks: Landmark[]; pitch_length_m: number; pitch_width_m: number }
  | { reuse_calibration_id: string };

export const getFrame = (sessionId: string, videoId: string, tMs: number) =>
  apiFetch<Frame>(`/sessions/${sessionId}/videos/${videoId}/frame?t_ms=${tMs}`);

export const saveCalibration = (sessionId: string, body: CalibrationBody) =>
  apiFetch<CalibrationSaved>(`/sessions/${sessionId}/calibration`, { method: "POST", body: JSON.stringify(body) });

/** Newest first. */
export const listCalibrations = (cameraId: string) => apiFetch<Page<Calibration>>(`/cameras/${cameraId}/calibrations`);
