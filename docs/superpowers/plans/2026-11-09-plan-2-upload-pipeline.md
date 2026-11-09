# VisionGuard V1 — Plan 2: Upload Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A coach can create a session, upload one or more phone videos resumably, calibrate the pitch, and get an analysed session: a 720p proxy, tracked players and ball, teams, projected metrics, `tracks.parquet` and `summary.json`, with progress shown in the dashboard.

**Architecture:** Sessions and their videos live in PostgreSQL. Uploads use a minimal in-house tus 1.0 server on the FastAPI backend, staged inside the media volume. A `process_session` RQ job on the `sessions` queue transcodes the proxy, then samples the original at `ANALYSIS_SAMPLE_FPS`. It runs RF-DETR Nano through ONNX Runtime, tracks with supervision's ByteTrack, assigns teams from torso colour, and writes `tracks.parquet`. A separate `compute_session_metrics` job projects the tracks through the saved calibration and writes per-track metrics and `summary.json`. It reruns whenever the calibration changes. The dashboard gets a Sessions page (create, upload, progress) and a calibration screen.

**Tech Stack:** Plan 1 stack, plus `onnxruntime`, `supervision` (ByteTrack only), `opencv-python-headless`, `numpy`, `scipy`, `pyarrow`, and the ffmpeg CLI. Dashboard adds `tus-js-client`.

**Spec:** `docs/superpowers/specs/2026-11-07-visionguard-v1-design.md` §5 (media storage), §7 (upload mode, session lifecycle, quality gates, performance), §8 (data model). Read Plan 1 (`2026-11-07-plan-1-foundation.md`) for the conventions this plan reuses.

### Plan series
| Plan | Covers | Ends with |
|---|---|---|
| 1. Foundation | M0 + M1 | done except the Task 13 benchmark verdict |
| **2. Upload pipeline (this)** | M2 | Upload → transcode → detect/track → teams → calibration → metrics, plus upload/calibration UI |
| 3. Review & tagging | M3 | Review screen, tagger, drills, labelling/merge, clips, share links → **academy pilot** |
| 4. Live mode | M4 | Frigate ingestion, rule engine, incidents, Telegram → **live pilot** |
| 5. Relay & hardening | M5 | Relay, retention/deletion, backups, hardening, docs update |

### Gate
Plan 1 Task 13 (the M0 benchmark) has **no verdict yet**. Tasks 1–11 don't depend on it, because their tests use a scripted fake detector and synthetic video. **Task 12 (model export + acceptance) must not start until `spikes/m0-benchmark/RESULTS.md` says GO or GO-with-tiling.** The verdict sets the defaults of `ANALYSIS_SAMPLE_FPS` and `ANALYSIS_TILE_FAR_HALF` (Task 1 creates both settings with defaults `10.0` / `false`). On NO-GO, stop and bring RESULTS.md to the owner.

## Global Constraints

- Everything in Plan 1's Global Constraints still holds: Python 3.11, roles, 404 for other tenants, RFC 9457 errors, cursor pagination, pinned versions, Alembic owns the schema, relative 0–1 image coordinates, `Africa/Kigali`.
- **Upload-mode processing is strictly local.** No Colab, no foreign cloud, no network calls from the pipeline (spec §3, §9).
- Detection uses RF-DETR Nano COCO weights (Apache-2.0) through **ONNX Runtime CPU**. Classes used: `person` and `sports ball`, confidence `0.3`. **No Ultralytics.** The backend never imports `torch` or `rfdetr`; only the export script (spike env) does.
- Tracking uses ByteTrack from `supervision` (MIT). Override supervision's `opencv-python` dependency so that only `opencv-python-headless` is installed (Task 5 shows how).
- Licence allowlist: shipped deps must be MIT/BSD/Apache-2.0 (plus the permissive set Plan 1 already accepted). **Pillow is HPND**, a permissive OSI licence that is not yet on the list. Task 5 adds `HPND` to `scripts/check_python_licenses.py` and flags it to the owner in the ledger as a ruling.
- Sample rate `ANALYSIS_SAMPLE_FPS` default `10.0`. Proxy is 720p H.264 for **playback only**; analysis reads the **original**.
- Max upload `10 GiB` per file (`10 * 1024**3` bytes). Sessions accept several files; they are ordered by `creation_time` metadata, with manual reorder.
- Pitch default `100 × 64` m. Pitch coordinates: `x` along the length `0..L`, `y` across the width `0..W`, metres. Calibration takes exactly 4 point pairs.
- Speeds above `36 km/h` are tracking errors: those steps are excluded. Sprint threshold default `19 km/h`, stored **per session**: the spec says per squad, but squads aren't modelled until Plan 3. Ledger this as a ruling. Distance and speed are approximate ("≈" in the UI).
- Per-frame track data goes to Parquet, **never PostgreSQL**. Storage keys (spec §5):
  `sessions/{customer_id}/{session_id}/source/{video_id}.mp4`, `.../proxy/{video_id}.mp4`, `.../analysis/tracks.parquet`, `.../analysis/summary.json`. Calibration frames go to `.../analysis/frame_{video_id}_{t_ms}.jpg`.
- Session status values are exactly `uploading | queued | processing | ready | failed` (spec §8).
- Roles: creating, uploading, calibrating and processing need `operator` or `customer_admin` (super_admin always passes). Reads are open to any role.
- **ffmpeg/ffprobe must be on PATH for the test suite** (host and CI). Tests generate their own clips with `ffmpeg -f lavfi`; no footage is committed.
- Host disk is about 3 GB free. The new backend deps add about 400 MB to the venv and the image. Run `docker builder prune -f` after image builds.

## Review Focus

1. **A dropped Wi-Fi connection mid-chunk.** The server must resume from the bytes actually on disk, not from a counter that ran ahead. HEAD reports the staging file's real size. → Task 3, `test_head_reports_bytes_on_disk_after_interrupted_patch`.
2. **A phone video with rotation metadata** (portrait, or upside-down landscape). Probe must report the displayed width/height, and frames/proxy must come out upright. → Task 2, `test_probe_and_frames_respect_display_rotation`.
3. **A video with no `creation_time`** (forwarded via WhatsApp, or edited). It must still upload and order after timed videos, in upload order, without errors. → Task 3, `test_videos_without_creation_time_order_after_timed_ones`.
4. **The wrong file picked** (a photo, a PDF, a truncated mp4). The video is marked `failed` with a human message, the session can't be processed until it's removed, and the server doesn't crash. → Task 3, `test_non_video_upload_is_marked_failed_and_blocks_processing`.
5. **A degenerate calibration click** (3 collinear points, or corners clicked in an order that makes a self-intersecting "bow-tie"). It's rejected with 422 and a message saying what's wrong, rather than producing garbage metrics. → Task 4, `test_collinear_or_bowtie_points_are_422`.

---

### Task 0: Owner setup (manual)

- [ ] **Step 1:** `sudo apt-get install -y ffmpeg`. Verify: `ffprobe -version` prints a version ≥ 6.1 (needed for `-display_rotation` in tests).
- [ ] **Step 2:** Free disk to at least 4 GB on `/` (`docker builder prune -f`, remove unused images).
- [ ] **Step 3:** Finish Plan 1 Task 13 (clip at `~/vg-footage/test-session.mp4`, run the benchmark, write the verdict). Needed before Task 12.

---

### Task 1: Session data model

**Files:**
- Create: `backend/migrations/versions/0003_sessions.py`, `backend/app/models/sessions.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/config.py`
- Test: `backend/tests/test_session_models.py`

**Interfaces:**
- Produces tables (all with `customer_id` FK → customers, `ON DELETE CASCADE`):
  - `calibrations(id, customer_id, camera_id → cameras CASCADE, image_points JSONB, pitch_points JSONB, pitch_length_m NUMERIC(5,1), pitch_width_m NUMERIC(5,1), created_by → users SET NULL, created_at)`
  - `sessions(id, customer_id, site_id → sites CASCADE, source_id → cameras RESTRICT, type VARCHAR(10) CHECK in ('training','match'), starts_at TIMESTAMPTZ NOT NULL, title VARCHAR(255), squad VARCHAR(100), status VARCHAR(12) NOT NULL DEFAULT 'uploading' CHECK in the five statuses, progress SMALLINT NOT NULL DEFAULT 0 CHECK 0..100, stage VARCHAR(20), error TEXT, sync_offset_ms INTEGER NOT NULL DEFAULT 0, sprint_threshold_kmh NUMERIC(4,1) NOT NULL DEFAULT 19.0 CHECK 5..40, calibration_id → calibrations SET NULL, quality JSONB, summary_key TEXT, created_by → users SET NULL, created_at, updated_at)`. Index `(customer_id, starts_at DESC)`.
  - `session_videos(id, customer_id, session_id → sessions CASCADE, position SMALLINT NOT NULL, original_filename VARCHAR(255), size_bytes BIGINT NOT NULL CHECK > 0, original_key TEXT NOT NULL, proxy_key TEXT, duration_ms INTEGER, fps NUMERIC(6,3), width INTEGER, height INTEGER, creation_time TIMESTAMPTZ, status VARCHAR(10) NOT NULL DEFAULT 'uploading' CHECK in ('uploading','uploaded','failed','processed'), error TEXT, created_at)`. Unique `(session_id, position)` **DEFERRABLE INITIALLY DEFERRED**, so reorders can swap positions in one transaction.
  - `session_tracks(id, customer_id, session_id → sessions CASCADE, track_id INTEGER NOT NULL, cls VARCHAR(10) CHECK in ('person','ball'), team VARCHAR(5) CHECK in ('a','b','other'), team_corrected BOOLEAN NOT NULL DEFAULT false, on_pitch BOOLEAN, frames_count INTEGER NOT NULL, first_ms INTEGER NOT NULL, last_ms INTEGER NOT NULL, metrics JSONB)`. Unique `(session_id, track_id)`. (Plan 3 adds `player_id` and `merged_into`.)
- Produces ORM classes `Calibration`, `Session`, `SessionVideo`, `SessionTrack` in `app/models/sessions.py`, using the `_types.py` helpers. The class is named `Session` in models; import it as `from app.models import Session as TrainingSession` wherever it would clash with SQLAlchemy's `AsyncSession` naming.
- Produces settings: `analysis_sample_fps: float = 10.0`, `analysis_tile_far_half: bool = False`, `analysis_threshold: float = 0.3`, `analysis_model_path: Path = Path("/app/models/rfdetr-nano.onnx")`, `max_upload_bytes: int = 10 * 1024**3`, `quality_min_players: int = 10`.

- [ ] **Step 1: Write failing tests**: `test_session_defaults` (new session → `status == "uploading"`, `progress == 0`, `sprint_threshold_kmh == 19.0`, `sync_offset_ms == 0`); `test_session_status_is_constrained` (raw UPDATE to `'done'` → IntegrityError); `test_video_positions_can_swap_in_one_transaction` (two videos at 0 and 1, swap, flush, commit savepoint → no error); `test_session_tracks_unique_per_session`; `test_deleting_session_cascades_videos_and_tracks`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_session_models.py -v` → FAIL (`ImportError`).
- [ ] **Step 3: Implement** migration 0003 (hand-written SQL via `op.execute`, with a full downgrade) and the ORM models and settings.
- [ ] **Step 4: Run** the file → PASS. Then `uv run alembic downgrade 0002 && uv run alembic upgrade head` against the test DB → no errors. Then `uv run pytest -q` → all green.
- [ ] **Step 5: Commit** `feat(db): sessions, session videos, calibrations and session tracks`

---

### Task 2: Video toolkit (ffprobe/ffmpeg wrapper)

**Files:**
- Create: `backend/app/video/__init__.py`, `backend/app/video/ffmpeg.py`
- Create: `backend/tests/media.py` (test helper: `make_clip(path, seconds=3, size="640x360", fps=25, creation_time: str | None = "2026-11-01T09:00:00Z", rotation: int | None = None) -> Path`, using `ffmpeg -f lavfi -i testsrc2=...` + `-c:v libx264 -pix_fmt yuv420p`, with `-display_rotation` as an input option when `rotation` is set and `-metadata creation_time=` when given)
- Test: `backend/tests/test_video.py`

**Interfaces:**
- Produces `class VideoError(Exception)`.
- Produces `@dataclass(frozen=True) class VideoInfo: duration_ms: int; fps: float; width: int; height: int; creation_time: datetime | None; codec: str`. Width/height are **display** dimensions (swapped for ±90° rotation).
- Produces `probe(path: Path) -> VideoInfo`: runs `ffprobe -v error -print_format json -show_streams -show_format`. Raises `VideoError("not a readable video")` when there's no video stream or ffprobe fails. `creation_time` comes from format tags, then stream tags, else `None`.
- Produces `transcode_proxy(src: Path, dest: Path, on_progress: Callable[[float], None] | None = None) -> None`: H.264 `libx264 -preset veryfast -crf 23`, scale to height 720 **only if taller** (`scale=-2:'min(720,ih)'`), AAC 96k if audio exists, `-movflags +faststart`. Writes to `dest.with_suffix(".tmp.mp4")` and then renames. Progress (0–1) comes from `-progress pipe:1` `out_time_us` against the duration.
- Produces `extract_frame(src: Path, t_ms: int, dest: Path) -> None` (JPEG, quality `-q:v 3`, display orientation).
- Produces `iter_frames(src: Path, sample_fps: float) -> Iterator[tuple[int, np.ndarray]]`: yields `(t_ms, frame_bgr)` at full display resolution, using `ffmpeg -i src -vf fps={sample_fps} -f rawvideo -pix_fmt bgr24 pipe:1`. `t_ms = round(i * 1000 / sample_fps)`. It kills the ffmpeg process if the consumer stops early.

- [ ] **Step 1: Write failing tests**
```python
def test_probe_reads_basic_info(tmp_path):
    info = probe(make_clip(tmp_path / "a.mp4", seconds=3, size="640x360", fps=25))
    assert (info.width, info.height) == (640, 360) and abs(info.fps - 25) < 0.01
    assert 2900 <= info.duration_ms <= 3100
    assert info.creation_time == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
def test_probe_without_creation_time_is_none(tmp_path): ...       # creation_time=None
def test_probe_rejects_non_video(tmp_path): ...                   # a .mp4 that is text → VideoError
def test_probe_and_frames_respect_display_rotation(tmp_path):     # Review Focus 2
    clip = make_clip(tmp_path / "r.mp4", size="640x360", rotation=90)
    assert (probe(clip).width, probe(clip).height) == (360, 640)
    t, frame = next(iter_frames(clip, 10))
    assert frame.shape[:2] == (640, 360)
def test_iter_frames_samples_at_requested_fps(tmp_path): ...      # 3 s @ 10 fps → 30 frames, t_ms 0,100,...,2900
def test_transcode_proxy_caps_height_and_never_upscales(tmp_path): ...  # 1920x1080 → 1280x720; 640x360 stays 640x360
def test_extract_frame_writes_jpeg(tmp_path): ...                 # file starts with b"\xff\xd8"
```
- [ ] **Step 2: Run** `uv run pytest tests/test_video.py -v` → FAIL (`ModuleNotFoundError: app.video`).
- [ ] **Step 3: Implement** per the Interfaces block. Use `subprocess.run`/`Popen` with argument lists (never `shell=True`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(video): ffprobe/ffmpeg toolkit for probing, proxies, frames and sampling`

---

### Task 3: Sessions API and resumable upload (tus 1.0)

**Files:**
- Create: `backend/app/sessions/{__init__,schemas,router,service}.py`, `backend/app/uploads/{__init__,router,staging}.py`
- Modify: `backend/app/storage/base.py`, `backend/app/storage/local.py` (add `import_file`), `backend/app/main.py`, `backend/app/worker/queues.py`
- Test: `backend/tests/test_sessions_api.py`, `backend/tests/test_uploads.py`

**Interfaces:**
- Consumes: Task 1 models; Task 2 `probe`, `VideoError`; Plan 1 `scoped`, `get_scoped_or_404`, `record_audit`, `paginate`, `require_roles`, `get_storage`.
- Produces `Storage.import_file(key: str, src: Path) -> int`: moves `src` into the store (an atomic `os.replace` for local storage) and returns its size.
- Produces in `queues.py`: `def get_sessions_queue() -> rq.Queue` (FastAPI dependency; tests override it with a FakeRedis-backed queue).
- Produces in `sessions/service.py`: `session_prefix(s) -> str` (`f"sessions/{s.customer_id}/{s.id}"`); `async def reorder_by_creation_time(db, session_id) -> None` (timed videos first by `creation_time`, then untimed by `created_at`; positions renumbered from 0); `def ensure_processable(s, videos) -> None` (422 `not-processable` unless there's ≥1 video and all are `uploaded`/`processed`, and status is `uploading|ready|failed`).
- Endpoints (`/api/v1`):
  - `POST /sessions` `{site_id, source_id, type, starts_at, title?, squad?, sprint_threshold_kmh?}` → 201. `source_id` must be a camera of the same site with `mode="upload"` (otherwise 422 `validation`, field `source_id`). The site must be visible to the caller (otherwise 404). `customer_id` is copied from the site. Audited `session.create`.
  - `GET /sessions?site_id=&status=` (Page, newest `starts_at` first: paginate on `created_at` as in Plan 1), `GET /sessions/{id}` (includes `videos: [...]` ordered by position), `PATCH /sessions/{id}` (`title, squad, starts_at, type, sprint_threshold_kmh`). A changed `sprint_threshold_kmh` on a `ready`, calibrated session enqueues `compute_session_metrics` (Task 9).
  - `PUT /sessions/{id}/video-order` `{video_ids: [...]}` → must be exactly the session's video ids, otherwise 422. Returns the session.
  - `POST /sessions/{id}/process` → runs `ensure_processable`, sets `status="queued", progress=0, stage=None, error=None`, then `get_sessions_queue().enqueue("app.worker.session_jobs.process_session", str(id), job_timeout=12*3600, result_ttl=86400)` → 202. Audited `session.process`.
- tus endpoints (`app/uploads/router.py`; every response carries `Tus-Resumable: 1.0.0`; requests other than OPTIONS without `Tus-Resumable: 1.0.0` → 412):
  - `OPTIONS /uploads` → 204, `Tus-Version: 1.0.0`, `Tus-Extension: creation,termination`, `Tus-Max-Size: <max_upload_bytes>`.
  - `POST /uploads` with `Upload-Length` and `Upload-Metadata` (`session_id`, `filename`, base64 per tus). Upload-Length over the max → 413 `too-large`. The session must be visible (404) and in `uploading|ready|failed`. Creates a `SessionVideo` (status `uploading`, `position` = current count, `original_key = {prefix}/source/{video_id}.mp4`) and an empty staging file `{media_root}/_uploads/{video_id}.part`. → 201 with `Location: /api/v1/uploads/{video_id}`.
  - `HEAD /uploads/{id}` → 200 with `Upload-Offset` = **size of the staging file on disk**, `Upload-Length`, `Cache-Control: no-store`.
  - `PATCH /uploads/{id}` (`Content-Type: application/offset+octet-stream`, `Upload-Offset`): take a row lock (`SELECT … FOR UPDATE`). An offset that differs from the on-disk size → 409 `offset-mismatch`. Stream `request.stream()` to the file in append mode, `fsync`, and never write past `Upload-Length` (→ 400). → 204 with the new `Upload-Offset`. When the offset reaches the length: `probe`. On `VideoError`, set status `failed`, `error="This file isn't a readable video."`, delete the staging file, and respond **422** `not-a-video`. Otherwise `storage.import_file(original_key, staging)`, fill `duration_ms/fps/width/height/creation_time`, set status `uploaded`, `reorder_by_creation_time`, and audit `session.upload`.
  - `DELETE /uploads/{id}` → 204. Removes the staging file, the stored original (if any) and the row; renumbers positions. Allowed for `uploading` and `failed` videos, and for any video while the session isn't `queued|processing` (otherwise 409).
- All tus routes use Bearer auth (tus-js-client sends `headers`) and the same roles as session writes. Another tenant's upload id → 404.

- [ ] **Step 1: Write failing tests**

```python
# test_sessions_api.py
async def test_operator_creates_session_on_upload_source(...)          # 201, status "uploading", customer_id from site
async def test_source_must_be_upload_mode_on_same_site(...)            # live camera → 422; other site's source → 422
async def test_viewer_cannot_create_or_process(...)                    # 403
async def test_other_customers_session_is_404(...)                     # GET/PATCH/process/video-order
async def test_list_filters_by_site_and_status(...)
async def test_process_requires_uploaded_videos_and_enqueues(...)     # none → 422 not-processable; after upload → 202, status queued, one job on fake sessions queue named process_session
async def test_video_order_must_be_a_permutation(...)                 # missing/extra id → 422; valid swap persists
# test_uploads.py  (helper: tus_upload(client, headers, session_id, data, chunk=…) drives POST/PATCH)
async def test_options_advertises_tus_and_max_size(...)
async def test_full_upload_in_chunks_stores_original_and_probes(...)   # 3 chunks; video uploaded; original_key exists in storage; duration/fps/size filled
async def test_upload_length_over_10_gib_is_413(...)                  # Upload-Length 10*1024**3 + 1
async def test_patch_with_wrong_offset_is_409(...)
async def test_head_reports_bytes_on_disk_after_interrupted_patch(...) # Review Focus 1: append 1000 bytes directly to the .part file → HEAD says 1000; PATCH at 1000 continues
async def test_missing_tus_resumable_header_is_412(...)
async def test_videos_without_creation_time_order_after_timed_ones(...)  # Review Focus 3: upload untimed A, timed 10:00 B, timed 09:00 C → order C, B, A
async def test_non_video_upload_is_marked_failed_and_blocks_processing(...)  # Review Focus 4: 422 not-a-video; process → 422; DELETE it → process → 202
async def test_other_customers_upload_is_404(...)
async def test_delete_upload_renumbers_positions(...)
```
Clips come from `tests/media.py::make_clip`. The `client` fixture gets a `media_root` under `tmp_path` (override `get_storage` and `get_settings().media_root` via a fixture in `conftest.py`, `media_storage`).
- [ ] **Step 2: Run** `uv run pytest tests/test_sessions_api.py tests/test_uploads.py -v` → FAIL.
- [ ] **Step 3: Implement** per the Interfaces block. `nginx.conf` already has `client_max_body_size 0` and `proxy_request_buffering off` (Plan 1 Task 11); verify both are present.
- [ ] **Step 4: Run** the two files → PASS. Then `uv run pytest -q` → all green.
- [ ] **Step 5: Commit** `feat(sessions): sessions API and resumable tus uploads`

---

### Task 4: Pitch calibration

**Files:**
- Create: `backend/app/analysis/__init__.py`, `backend/app/analysis/pitch.py`, `backend/app/sessions/calibration.py` (router)
- Modify: `backend/app/main.py`, `backend/pyproject.toml` (add `numpy==2.2.6`, `opencv-python-headless==4.11.0.86`)
- Test: `backend/tests/test_pitch.py`, `backend/tests/test_calibration_api.py`

**Interfaces:**
- Produces in `pitch.py`: `class CalibrationError(ValueError)`; `LANDMARKS: dict[str, Callable[[float, float], tuple[float, float]]]` with keys `corner_near_left (0,0)`, `corner_near_right (L,0)`, `corner_far_right (L,W)`, `corner_far_left (0,W)`, `halfway_near (L/2,0)`, `halfway_far (L/2,W)`, `centre_spot (L/2,W/2)`, `penalty_spot_left (11,W/2)`, `penalty_spot_right (L-11,W/2)`; `fit_homography(image_pts: list[tuple[float,float]], pitch_pts: list[tuple[float,float]]) -> np.ndarray` (3×3, image-relative → metres, via `cv2.getPerspectiveTransform`); `project(H: np.ndarray, pts: np.ndarray) -> np.ndarray` (N×2 → N×2; points that land behind the camera, i.e. homogeneous w ≤ 0, become NaN).
- `fit_homography` raises `CalibrationError` with these messages:
  - `"Exactly 4 points are needed"` when the count isn't 4.
  - `"Image points must be inside the frame"` when an image point is outside 0..1.
  - `"Three of the points are on one line; pick points spread around the pitch"` when any 3 image points (triangle area < 0.002) or pitch points (area < 1 m²) are collinear.
  - `"The points cross over; click them in the same order as the pitch points"` when the image quadrilateral and the pitch quadrilateral, each taken in the given order, aren't both simple (non-self-intersecting) with the same orientation sign.
- Endpoints:
  - `GET /sessions/{id}/videos/{video_id}/frame?t_ms=0` → extracts (cached) `{prefix}/analysis/frame_{video_id}_{t_ms}.jpg` from the **original**. Returns `{"url": sign_media_url(key, ttl_seconds=900), "width", "height"}`. Requires the video to be `uploaded|processed` (otherwise 409).
  - `POST /sessions/{id}/calibration` `{image_points: [[x,y]×4], landmarks: [str×4]?, pitch_points: [[x,y]×4]?, pitch_length_m=100, pitch_width_m=64}` **or** `{reuse_calibration_id}`. Exactly one of `landmarks`/`pitch_points` (landmarks resolve through `LANDMARKS` using the pitch size). Validates with `fit_homography` (`CalibrationError` → 422 `invalid-calibration` with the message as `detail`). Creates a `Calibration` with `camera_id = session.source_id`; a reused one must belong to the same source (otherwise 404). Sets `session.calibration_id`, audits `calibration.save`, and enqueues `compute_session_metrics` when the session is `ready`. → 201 `{calibration, session}`.
  - `GET /cameras/{id}/calibrations` → Page of that source's calibrations, newest first (for the "reuse previous" offer).
- Roles: frame GET, any role; calibration POST, operator+.

- [ ] **Step 1: Write failing tests**
```python
# test_pitch.py
def test_homography_maps_clicked_points_to_pitch_points():
    img = [(0.1, 0.9), (0.9, 0.9), (0.7, 0.3), (0.3, 0.3)]
    pitch = [(0, 0), (100, 0), (100, 64), (0, 64)]
    H = fit_homography(img, pitch)
    assert np.allclose(project(H, np.array(img)), np.array(pitch), atol=1e-6)
def test_landmarks_scale_with_pitch_size(): ...        # LANDMARKS["halfway_far"](60, 40) == (30, 40)
@pytest.mark.parametrize("img,msg", [...])            # collinear and bow-tie
def test_collinear_or_bowtie_points_are_rejected(img, msg): ...  # Review Focus 5 (unit)
def test_points_outside_frame_are_rejected(): ...
# test_calibration_api.py
async def test_save_calibration_with_landmarks_sets_session_calibration(...)
async def test_collinear_or_bowtie_points_are_422(...)  # Review Focus 5 (API): detail contains "on one line" / "cross over"
async def test_reuse_previous_calibration_from_same_source(...)  # second session on same source reuses → same calibration id; other source → 404
async def test_calibration_on_ready_session_enqueues_metrics(...)
async def test_frame_endpoint_returns_signed_jpeg_url(...)  # GET the url → 200 image/jpeg
async def test_viewer_cannot_calibrate(...)
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the two files, then the whole suite → PASS.
- [ ] **Step 5: Commit** `feat(calibration): pitch homography, landmarks, calibration API with reuse`

---

### Task 5: Detector interface, far-half tiling and ML dependencies

**Files:**
- Create: `backend/app/analysis/detector.py`
- Modify: `backend/pyproject.toml` (add `onnxruntime==1.20.1`, `supervision==0.26.1`, `scipy==1.15.1`, `pyarrow==18.1.0`; add `[tool.uv] override-dependencies = ["opencv-python; sys_platform == 'never'"]` so only the headless OpenCV is installed), `scripts/check_python_licenses.py` (allow `HPND`), `.github/workflows/ci.yml` (`sudo apt-get install -y ffmpeg` in the backend job), `.gitignore` (already ignores `/models/`)
- Test: `backend/tests/test_detector.py`

**Interfaces:**
- Model metadata contract (written by Task 12's export script, read here): `models/rfdetr-nano.json` = `{"input_name", "resolution", "mean", "std", "boxes_output", "logits_output", "box_format": "cxcywh_norm", "class_ids": {"person": <id>, "sports ball": <id>}}`.
- Produces in `detector.py`:
  - `PERSON, BALL = 0, 1`
  - `@dataclass(frozen=True) class Detections: xyxy: np.ndarray  # (N,4) float32, relative 0–1` · `score: np.ndarray  # (N,)` · `cls: np.ndarray  # (N,) int8, PERSON|BALL`, with `@staticmethod empty() -> Detections`
  - `class Detector(Protocol): def detect(self, frame_bgr: np.ndarray) -> Detections`
  - `class OnnxRfDetr` with `__init__(self, model_path: Path, threshold: float = 0.3)` (reads the sibling `.json`). It uses `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])` with `intra_op_num_threads = os.cpu_count()`, keeps person/ball only, and applies a sigmoid to the logits.
  - `def detect_with_far_half_tiling(detector: Detector, frame_bgr: np.ndarray) -> Detections`: detects on the full frame **and** on the top half upscaled 2×, maps the tile boxes back, and merges per class with NMS at IoU 0.5 (`cv2.dnn.NMSBoxes`).
  - `def get_detector() -> Detector`: `OnnxRfDetr(settings.analysis_model_path, settings.analysis_threshold)`; a missing file → `RuntimeError("Detection model not found at …; see plan 2 Task 5")`.

- [ ] **Step 1: Write failing tests**: `test_tiling_merges_duplicate_boxes_with_nms` (a fake detector returns the same person on the full frame and in the tile → one box); `test_tiling_maps_tile_boxes_back_to_frame_coordinates` (a box at tile-relative (0.5,0.5,0.6,0.7) → frame (0.5,0.25,0.6,0.35)); `test_missing_model_raises_clear_error`; `test_detections_empty_has_right_shapes`. Also add `@pytest.mark.model test_onnx_detector_finds_people_on_real_frame`. It's skipped unless `models/rfdetr-nano.onnx` exists; it extracts the frame at 60 s of `~/vg-footage/test-session.mp4` and expects ≥ 5 persons. It runs for real in Task 12. Register the `model` marker in `pyproject.toml`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Then `uv lock && uv sync`, and verify `uv run python -c "import cv2, supervision, onnxruntime; print(cv2.__version__)"` prints `4.11.0` and that `uv pip list | grep -i opencv` shows **only** `opencv-python-headless`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS. Run `python ../scripts/check_python_licenses.py` against the prod env → `All licenses allowed`. **Ledger ruling:** HPND (Pillow, pulled in by supervision) added to the allowlist, for the owner to confirm.
- [ ] **Step 5: Commit** `feat(analysis): detector interface, ONNX RF-DETR runner and far-half tiling`

---

### Task 6: Frame sampling and tracking → `tracks.parquet`

**Files:**
- Create: `backend/app/analysis/tracking.py`, `backend/app/analysis/tracks_io.py`
- Test: `backend/tests/test_tracking.py`

**Interfaces:**
- Consumes: Task 2 `iter_frames`; Task 5 `Detector`, `Detections`, `detect_with_far_half_tiling`, `PERSON`, `BALL`.
- Produces in `tracks_io.py`: `TRACKS_SCHEMA` (pyarrow): `video_id: string, t_ms: int64 (session timeline), track_id: int32, cls: int8, x1,y1,x2,y2: float32 (relative), score: float32`. Also `write_tracks(rows: pa.Table, dest: Path) -> None` (zstd) and `read_tracks(path: Path) -> pa.Table`.
- Produces in `tracking.py`:
  - `@dataclass class VideoAnalysis: table: pa.Table; torso_samples: dict[int, list[np.ndarray]]  # track_id → up to 20 RGB torso crops resized to 16×16; frames: int; persons_per_frame: list[int]`
  - `def analyse_video(path: Path, video_id: str, detector: Detector, sample_fps: float, t_offset_ms: int, first_track_id: int, tile_far_half: bool = False, on_progress: Callable[[float], None] | None = None) -> VideoAnalysis`. It uses one `sv.ByteTrack(frame_rate=round(sample_fps))` for persons and a separate one for the ball. Detections are converted to pixel coordinates for supervision and back to relative. Track ids are renumbered to consecutive session-unique ids starting at `first_track_id`. The torso crop is the box region from 20–55 % of its height and 25–75 % of its width; reservoir sampling (seeded with the track id) keeps it at ≤ 20. Progress = processed frames / expected frames (`duration × sample_fps`).

- [ ] **Step 1: Write failing tests** with a `ScriptedDetector` test double (in `tests/fakes.py`) that returns, per frame index, the boxes of two "players" moving right at a constant speed plus a ball:
  - `test_two_moving_players_keep_stable_ids` (exactly 2 person track ids across 30 frames, each with 30 rows, x increasing)
  - `test_track_ids_are_offset_for_session_uniqueness` (`first_track_id=100` → ids ≥ 100)
  - `test_t_ms_includes_video_offset` (`t_offset_ms=60000` → first row 60000)
  - `test_ball_is_tracked_separately_from_people` (ball rows have `cls == BALL` and their own id)
  - `test_torso_samples_capped_at_20`
  - `test_parquet_roundtrip_keeps_schema`
  The clip is `make_clip(seconds=3, fps=25)` sampled at 10 fps.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(analysis): sampled detection + ByteTrack into session-unique tracks parquet`

---

### Task 7: Team assignment from torso colour

**Files:**
- Create: `backend/app/analysis/teams.py`
- Test: `backend/tests/test_teams.py`

**Interfaces:**
- Produces `def torso_feature(crops: list[np.ndarray]) -> np.ndarray | None`. It converts the crops to CIE Lab (OpenCV), drops grass-like pixels (HSV hue 35–85 on OpenCV's 0–179 scale with saturation > 60), and returns the per-channel median Lab of what's left. It returns `None` if fewer than 20 pixels remain.
- Produces `def assign_teams(features: dict[int, np.ndarray | None], frames_count: dict[int, int], min_frames: int = 10) -> dict[int, str]`, returning values in `{"a","b","other"}`:
  - Tracks with `None` features or fewer than `min_frames` frames → `other`.
  - Otherwise `scipy.cluster.vq.kmeans2(k=2, minit="++", seed=0)` on the Lab features.
  - A member whose distance to its centre is > `max(12.0, 2.0 × the cluster's median member distance)` → `other` (goalkeepers, referees, coaches).
  - `a` is the cluster with more members; on a tie, the one with the lower L.
  - With fewer than 4 eligible tracks, all are `other`.

- [ ] **Step 1: Write failing tests** with synthetic crops: solid red shirts ×6, solid blue ×6, yellow ×1 (referee), each with a green band of grass at the bottom.
  - `test_two_shirt_colours_split_into_a_and_b` (all reds share a team, all blues share the other, `a` is the 6-member side, deterministic across runs)
  - `test_odd_colour_goes_to_other`
  - `test_grass_pixels_are_ignored` (a red crop that's 70 % green still clusters with red)
  - `test_short_tracks_are_other`
  - `test_too_few_tracks_are_all_other`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(analysis): per-track team assignment from torso colour`

---

### Task 8: Metrics, pitch filter, quality and summary

**Files:**
- Create: `backend/app/analysis/metrics.py`, `backend/app/analysis/summary.py`
- Test: `backend/tests/test_metrics.py`

**Interfaces:**
- Consumes: Task 4 `project`; Task 6 `read_tracks` table layout.
- Constants: `SPEED_CAP_KMH = 36.0`, `BANDS_KMH = {"walk": (0, 7), "jog": (7, 14), "run": (14, sprint), "sprint": (sprint, ∞)}`, `GAP_BREAK_S = 1.0`, `SMOOTH_WINDOW = 5` (samples), `SPRINT_MIN_S = 1.0`, `PITCH_MARGIN_M = 2.0`, `ON_PITCH_MIN_FRACTION = 0.5`, `HEATMAP_SHAPE = (13, 20)` (rows across the width, columns along the length), `WINDOW_S = 10`.
- Produces `def foot_points(table) -> np.ndarray` (bottom-centre of each box, relative).
- Produces `def track_metrics(t_ms: np.ndarray, xy_m: np.ndarray, sprint_kmh: float, pitch: tuple[float, float]) -> dict`. Keys: `distance_m`, `top_speed_kmh`, `band_seconds` (walk/jog/run/sprint), `sprint_count`, `avg_x_m`, `avg_y_m`, `heatmap` (13×20 list of time fractions summing to 1), `samples`. How it works:
  - Split into segments wherever the gap is > `GAP_BREAK_S`.
  - Smooth positions with a centred moving average of `SMOOTH_WINDOW` (shrinking at the edges).
  - Step speed = distance / dt. Steps faster than the cap are excluded from distance, bands and top speed.
  - `top_speed_kmh` = max of the 1-second rolling mean of the remaining step speeds.
  - A sprint is a run of consecutive kept steps ≥ `sprint_kmh` lasting ≥ `SPRINT_MIN_S`.
- Produces `def is_on_pitch(xy_m: np.ndarray, pitch: tuple[float, float]) -> bool`: the fraction of non-NaN points inside the pitch grown by `PITCH_MARGIN_M` is ≥ `ON_PITCH_MIN_FRACTION`.
- Produces `def team_shape(...)`. In each 10 s window it takes each on-pitch team-`a`/`b` track's mean position and needs ≥ 3 tracks per team. It returns `width_m` (range across the y axis), `depth_m` (range along the x axis) and `compactness_m` (mean distance to the team centroid), or `None`.
- Produces `def intensity_timeline(...) -> list[dict]`: `[{"t_ms": window_start, "mean_speed_kmh": float | None}]`, the mean of the kept step speeds of on-pitch team-`a`/`b` tracks per 10 s window.
- Produces `def quality(persons_per_frame: list[int], track_lengths_s: list[float], calibrated: bool, min_players: int) -> dict`: `{"frames_with_min_players": fraction, "calibrated": bool, "mean_track_length_s": float}`.
- Produces in `summary.py`: `def build_summary(*, duration_ms, sample_fps, calibrated, quality, teams_overview, intensity, team_shape, tracks_total) -> dict` with `"version": 1`. `teams_overview` gives, per team, `players_on_pitch_avg`, `distance_m_total`, `heatmap`. Distance and speed fields carry `"approximate": true`.

- [ ] **Step 1: Write failing tests** (pure numpy, hand-computable):
```python
def test_constant_speed_track_distance_and_top_speed():
    # 20 s at 10 fps moving 5 m/s along x → ≈100 m, top ≈18 km/h, no sprint, all "run" band
def test_spike_above_cap_is_excluded():          # one 15 m jump in a steady 2 m/s walk → distance unchanged within 1 m, top speed < 36
def test_sprint_needs_one_second_above_threshold():  # 0.5 s at 25 km/h → 0 sprints; 2 s at 25 km/h → 1 sprint
def test_sprint_threshold_is_per_session():      # same track, sprint_kmh=15 vs 19 → different counts
def test_gaps_break_segments_without_teleport_distance():  # 3 s gap jumping 30 m → not counted
def test_heatmap_sums_to_one_and_lands_in_right_cell():
def test_is_on_pitch_with_margin():              # track at y = -1.5 m → on; at y = -5 m → off
def test_team_shape_needs_three_players():
def test_intensity_is_mean_speed_per_10s_window():
def test_quality_fraction_and_track_length():
def test_summary_marks_distances_approximate():
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(analysis): projected per-track and team metrics, quality and summary`

---

### Task 9: Processing jobs

**Files:**
- Create: `backend/app/worker/session_jobs.py`, `backend/app/worker/runtime.py`
- Modify: `backend/app/sessions/router.py` (add `GET /sessions/{id}/summary`, `GET /sessions/{id}/tracks`)
- Test: `backend/tests/test_session_jobs.py`

**Interfaces:**
- Produces in `runtime.py`: `def run_async(fn: Callable[[AsyncSession], Awaitable[T]]) -> T`. It runs the function with a fresh `create_async_engine(..., poolclass=NullPool)` session via `asyncio.run`, commits, and disposes. RQ jobs are sync.
- Produces in `session_jobs.py`:
  - `def process_session(session_id: str) -> None` and `def compute_session_metrics(session_id: str) -> None`: RQ entry points that call the async cores through `run_async(...)` with `get_storage()` and `get_detector()`.
  - `async def process_session_core(db, storage, detector, session_id: UUID, *, sample_fps: float, tile_far_half: bool) -> None`. It sets `status="processing"`, then:
    1. For each video in position order: `stage="transcoding"` → `transcode_proxy` to `{prefix}/proxy/{video_id}.mp4`, giving 20 % of that video's share of progress.
    2. `stage="analysing"` → `analyse_video` with `t_offset_ms` = the sum of the previous videos' `duration_ms` and `first_track_id` continuing from the last video, giving 75 %.
    3. `stage="teams"` → features and `assign_teams` across all videos, giving the last 5 %.
    4. Write `{prefix}/analysis/tracks.parquet`.
    5. Replace the `session_tracks` rows (delete, then insert with `team`, `frames_count`, `first_ms`, `last_ms`; `on_pitch`/`metrics` are null). Set videos to `processed`.
    6. If calibrated, call `compute_metrics_core`; otherwise write an uncalibrated summary (`calibrated: false`, quality with `calibrated: false`).
    7. Set `status="ready"`, `progress=100`, `stage=None`.
    Progress is written (in its own commit) only when it moves by ≥ 2 points. On any exception: `status="failed"`, `error` = a short message (`str(exc)[:500]`, no traceback), `stage` kept, then re-raise so RQ records the failure.
  - `async def compute_metrics_core(db, storage, session_id: UUID) -> None`. It reads `tracks.parquet` and the calibration, projects foot points, and fills `session_tracks.on_pitch/metrics` (persons only). Teams use `team` as stored, including `team_corrected` overrides. It then writes `summary.json`, sets `session.quality` and `session.summary_key`, and doesn't touch `status`.
- Endpoints:
  - `GET /sessions/{id}/summary` → 409 `not-ready` unless status is `ready`. Otherwise returns the summary JSON plus `"proxies": [{"video_id", "url": sign_media_url(proxy_key, ttl_seconds=3600), "t_offset_ms"}]`.
  - `GET /sessions/{id}/tracks?cls=person` → `[{track_id, cls, team, team_corrected, on_pitch, frames_count, first_ms, last_ms, metrics}]` (not paginated; one session is at most a few hundred tracks).

- [ ] **Step 1: Write failing tests** using `ScriptedDetector`, two `make_clip`s (2 s each, second with a later `creation_time`), `media_storage`, and `db_session`, calling the cores directly:
  - `test_process_produces_proxies_parquet_tracks_and_ready_status` (one proxy per video exists; parquet has rows from both videos with the second's `t_ms` ≥ 2000; `session_tracks` rows exist; status `ready`, progress 100)
  - `test_progress_is_monotonic_and_reaches_100` (record progress values via a spy on commits)
  - `test_uncalibrated_session_gets_summary_without_metrics`
  - `test_calibration_then_metrics_fills_track_metrics_and_summary` (save a calibration through the API, run `compute_metrics_core`, `summary["calibrated"] is True`, persons have `distance_m`)
  - `test_failure_marks_session_failed_with_short_error` (a detector that raises → status `failed`, error set, no traceback text)
  - `test_reprocess_replaces_tracks_not_duplicates`
  - `test_summary_endpoint_409_until_ready_then_signed_proxy_urls`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the file, then the whole suite → PASS.
- [ ] **Step 5: Commit** `feat(worker): session processing and metrics jobs with progress`

---

### Task 10: Dashboard: sessions list, new session, upload, progress

**Files:**
- Modify: `dashboard/package.json` (add `tus-js-client@4.2.3`), `dashboard/src/App.tsx` (routes `sessions`, `sessions/new`, `sessions/:id`), `dashboard/src/pages/Sessions.tsx`
- Create: `dashboard/src/sessions/{api.ts, SessionList.tsx, NewSessionForm.tsx, SessionDetail.tsx, UploadPanel.tsx, ProgressBadge.tsx, sessions.test.tsx}`

**Interfaces:**
- Consumes: Task 3 and 9 endpoints, Plan 1 `apiFetch` and `useAuth`, and `GET /sites` / `GET /cameras?site_id=&mode=upload` / `POST /cameras`.
- Produces in `api.ts`: typed wrappers `listSessions`, `getSession`, `createSession`, `processSession`, `setVideoOrder`, and `uploadFile(sessionId, file, {onProgress, onError, onSuccess}) => tus.Upload`. `uploadFile` sets `endpoint: "/api/v1/uploads"`, `chunkSize: 8 * 1024 * 1024`, `retryDelays: [0, 1000, 3000, 5000, 10000, 20000]`, `metadata: {session_id, filename}`, a `headers` getter that supplies the current access token, `removeFingerprintOnSuccess: true`, and calls `findPreviousUploads()` + `resumeFromPreviousUpload` so that re-selecting the same file resumes it.
- Behaviour:
  - **List:** title (or "Training · {date}"), site, status badge (`uploading` neutral, `queued`/`processing` warning with `{progress}%` and stage, `ready` success, `failed` danger with the error), newest first. Empty state copy is from UI doc §8 (already in `Sessions.tsx`).
  - **New session form:** site, pitch position (upload sources of that site), with "Add pitch position" when there are none (creates `mode: "upload", source_type: "phone"`); date/time defaulting to now in the site timezone; type training/match; optional title and squad.
  - **Detail page:** a file picker accepting `video/*` with multiple files; one row per file with a progress bar; reorder buttons (↑/↓) calling `setVideoOrder`; failed videos show the server message and a Remove button. "Start processing" is enabled only when every video is uploaded. While `queued|processing`, the session is polled every 5 s. "Calibrate pitch" links to Task 11's route. Copy: "Recording tip: phone high up at the halfway line, whole pitch in frame, landscape, 1080p."
  - Viewer role: no create/upload/process controls.

- [ ] **Step 1: Write failing tests** (Vitest + MSW, mocking `tus-js-client`'s `Upload` class with a fake that emits progress/success):
  - `test("lists sessions with status badges and progress")`
  - `test("new session form requires a pitch position and creates the session")`
  - `test("offers to add a pitch position when the site has none")`
  - `test("uploading two files shows per-file progress and enables Start processing when done")`
  - `test("a failed video shows the server message and a Remove button")`
  - `test("polls while processing and stops when ready")` (fake timers)
  - `test("viewer sees no upload or process controls")`
- [ ] **Step 2: Run** `npx vitest run` → FAIL. **Step 3: Implement.** **Step 4: Run** `npx vitest run && npx tsc --noEmit && npx vite build` → pass.
- [ ] **Step 5: Commit** `feat(dashboard): sessions list, creation, resumable upload and progress`

---

### Task 11: Dashboard: pitch calibration screen

**Files:**
- Create: `dashboard/src/sessions/{CalibrationPage.tsx, calibration.ts, calibration.test.tsx}`
- Modify: `dashboard/src/App.tsx` (route `sessions/:id/calibrate`)

**Interfaces:**
- Consumes: Task 4 endpoints.
- Produces in `calibration.ts`: `LANDMARK_LABELS` (same keys as backend `LANDMARKS`, with the labels "Near-left corner", "Near-right corner", "Far-right corner", "Far-left corner", "Halfway line (near)", "Halfway line (far)", "Centre spot", "Left penalty spot", "Right penalty spot") and `toRelative(clientX, clientY, imgRect) => [x, y]` (clamped 0–1).
- Behaviour:
  - Shows the frame from `GET …/frame?t_ms=0` of the first video, plus a time slider (0–60 s in 5 s steps) for when the first frame is unclear.
  - The coach clicks 4 points. Each point gets a landmark from a picker; the 4 default to the four corners in order. Numbered markers, draggable, with Undo and Reset.
  - Pitch length/width inputs, defaulting to 100 × 64.
  - If the source has a previous calibration: a "Use previous calibration ({date})" button.
  - Save shows the server's 422 `detail` inline. On success: "Calibration saved. Metrics will update in a few minutes." when the session is ready.
  - Keyboard: Backspace undoes the last point. Touch targets ≥ 44 px.

- [ ] **Step 1: Write failing tests**:
  - `test("clicking four points and saving posts relative coordinates and landmarks")` (asserts the request body)
  - `test("server 422 detail is shown inline")` (the collinear message)
  - `test("use previous calibration posts reuse_calibration_id")`
  - `test("cannot save with fewer than four points")`
  - `test("toRelative clamps to the image")`
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `npx vitest run && npx tsc --noEmit && npx vite build` → pass.
- [ ] **Step 5: Commit** `feat(dashboard): pitch calibration screen with landmarks and reuse`

---

### Task 12: Model export and acceptance run on real footage — **gated on the M0 verdict**

**Files:** Create `spikes/m0-benchmark/export_onnx.py` (spike env, which has torch). Append to `spikes/m0-benchmark/RESULTS.md`.

- [ ] **Step 1: Export.** `export_onnx.py --out ../../models/rfdetr-nano.onnx --check-video ~/vg-footage/test-session.mp4` exports RF-DETR Nano with `rfdetr`'s own ONNX export, then writes the Task 5 metadata JSON from values read off the PyTorch model. Before writing the JSON, it runs PyTorch and ONNX on 5 frames of the check video and **exits non-zero** unless person boxes match (IoU ≥ 0.9 for ≥ 95 % of PyTorch boxes with score ≥ 0.3). Run `cd spikes/m0-benchmark && uv run python export_onnx.py ...` → `parity OK`. Then `cd backend && uv run pytest -q -m model` → the real-frame test passes. Commit `spike: export RF-DETR Nano to ONNX with parity check`.
- [ ] **Step 2:** `docker compose up -d --build`, then `docker builder prune -f`. Copy the model files into `./models/` (mounted at `/app/models`). Run `bash scripts/smoke.sh` → `SMOKE OK`.
- [ ] **Step 3:** In the browser at `http://localhost:8501`, as an operator of a `sports` customer: create a session, upload `~/vg-footage/test-session.mp4`, and **kill the network mid-upload once**, then reconnect; the upload must resume, not restart (spec §11). Calibrate with 4 landmarks, then start processing.
- [ ] **Step 4:** When it's `ready`, open `GET /api/v1/sessions/{id}/summary` and `/tracks`. Check by eye: two teams of plausible size; on-pitch players' distances plausible for 5 minutes (roughly 300–700 m for active players); intensity timeline non-empty; quality filled.
- [ ] **Step 5:** Append to `spikes/m0-benchmark/RESULTS.md` under "Plan 2 acceptance": wall-clock time per stage, the projected time for 90 minutes on the laptop and on the N100 (×0.6, the same assumption as M0), team assignment correctness on 10 sampled track-minutes, and the quality values.
- [ ] **Step 6: Commit** `docs: plan 2 acceptance results on test footage`

---

## Definition of done (Plan 2)
- `uv run pytest -q` and `npx vitest run` are green, with ffmpeg on PATH (the model test runs locally when the model is present).
- In the browser, a coach can create a session, upload resumably (surviving a forced disconnect), calibrate, process, and get a `ready` session whose summary and tracks endpoints return teams and approximate metrics.
- `RESULTS.md` has the acceptance numbers. Any threshold the numbers suggest changing (sample fps, tiling, team thresholds) is ledgered for Plan 3.
