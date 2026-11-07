# Technical Architecture — VisionGuard AI

## 1. Architecture overview

```text
 +-------------------+      +---------------------------+
 | IP / USB / phone  | RTSP | Frigate NVR (per site)    |
 | cameras           |----->| go2rtc restream, motion,  |
 +-------------------+      | detection, tracking,      |
                            | recording, snapshots      |
 +-------------------+      +-------------+-------------+
 | Screen agent      |                    | MQTT  frigate/events, frigate/reviews
 | (capture + OCR)   |----+               v
 +-------------------+    |   +-----------------------+
                          +-->| Mosquitto (auth+ACL)  |
                              +-----------+-----------+
                                          |
                    +---------------------v----------------------+
                    | VisionGuard backend (FastAPI)              |
                    |  - Ingestor: normalises Frigate/screen msgs|
                    |  - Rule engine (single source of truth)    |
                    |  - REST API + WebSocket live events        |
                    +----+-------------------+-------------------+
                         | jobs (Valkey)     | publish visionguard/events/new
                    +----v-------------+     v
                    | Worker           |   +------------------------------+
                    | alerts + retries |   | Node-RED (optional)          |
                    | clip export      |   | customer integrations only:  |
                    | retention purge  |   | PLC, siren, POS              |
                    | training jobs    |   +------------------------------+
                    +----+-------------+
                         |
     +-------------------+---------------------+            +------------------------+
     | PostgreSQL | Object storage | Valkey    |            | Telegram | Email | SMS |
     | (metadata) | (local / S3)   | (state)   |            | Webhook                |
     +-------------------------------------------+          +------------------------+
                         |
              +----------v-----------+
              | Dashboard (Streamlit MVP -> React)  |
              +----------------------+
```

## 2. Key decisions (and why)

| Decision | Choice | Reason |
|---|---|---|
| Where rules are evaluated | **Backend only** | Evaluating rules in both Node-RED and the backend causes duplicate or contradictory alerts and splits audit logs. Node-RED only subscribes to `visionguard/events/#` for customer-specific integrations. |
| Detection & recording | Frigate per site | Mature NVR: restreaming, motion gating, tracking, recording, retention. We don't rebuild this. |
| Custom detection | Backend "vision worker" (OpenCV + ONNX Runtime) | For things Frigate can't express: screen monitoring, counting logic across frames, custom models not loaded into Frigate. |
| Object storage | **Local volume for MVP, S3-compatible later** | MinIO stopped publishing community Docker images in Oct 2025 and its community repo is in maintenance mode. A storage interface with `local` and `s3` backends keeps us vendor-neutral (SeaweedFS, Garage, AWS S3, Wasabi). |
| Queue / cache | Valkey (BSD-licensed Redis fork) | Job queue, rule state (persistence timers, cooldowns), live-event pub/sub. |
| Detection model licensing | **Apache-2.0 models for anything sold** (see §6) | Ultralytics YOLO is AGPL-3.0; commercial closed-source use requires an Enterprise licence. |
| Coordinates | Relative (0–1) everywhere | Zones survive changes in detect/record resolution and map directly to Frigate's relative zone format. |

## 3. Components

### Frigate NVR
- Connects RTSP/ONVIF cameras via go2rtc (one connection per camera, restreamed to detect, record and live view).
- Detects on the low-res sub-stream, records the high-res main stream.
- Publishes tracked-object updates on `frigate/events` and review items on `frigate/reviews`.
- Authenticated UI on port 8971; port 5000 stays internal.

### Backend (FastAPI)
- **Ingestor**: subscribes to `frigate/events`, maps Frigate camera/zone names to VisionGuard IDs, de-duplicates by `frigate_event_id`.
- **Rule engine**: evaluates `presence`, `count`, `dwell`, `absence`, `line_cross` and `screen` conditions with confidence, duration, schedule and cooldown. Rule state lives in Valkey, so it survives restarts.
- **API**: REST (`/api/v1`) + WebSocket (`/api/v1/ws/events`) for the live dashboard.
- **Model registry**: uploads, metrics, licence check, per-camera assignment, rollback.

### Worker
- Alert delivery with retries and exponential backoff (`alert_deliveries.next_attempt_at`).
- Pulls the snapshot and clip from Frigate's API into object storage when an event is raised.
- Nightly retention purge per customer (`customers.data_retention`).
- Training jobs (local CPU for tiny jobs; Colab or a remote GPU for real ones).

### Dashboard
- MVP: Streamlit (port 8501). Target: React + Vite following `16-ui-ux-design-document.pdf`.
- Live view embeds go2rtc WebRTC/MSE streams. Video does not pass through the backend.

### MQTT topics
| Topic | Publisher | Consumer |
|---|---|---|
| `frigate/events`, `frigate/reviews` | Frigate | Backend |
| `visionguard/events/new` | Backend | Node-RED, integrations |
| `visionguard/events/reviewed` | Backend | Node-RED, integrations |
| `visionguard/actions/requests` | Node-RED / integrations | Backend (validated, audited) |
| `visionguard/screens/{agent_id}/status` | Screen agent | Backend |

Each client has its own MQTT user and ACL (`mosquitto/config/acl.example`).

### PostgreSQL
Metadata only: tenants, users, sites, cameras, zones, rules, events, deliveries, actions, models, assignments, training jobs, feedback, audit log. See `04-database-schema.sql`.

### Object storage layout
```text
snapshots/{customer_id}/{yyyy}/{mm}/{dd}/{event_id}.jpg
clips/{customer_id}/{yyyy}/{mm}/{dd}/{event_id}.mp4
datasets/{customer_id}/{dataset_name}/...
models/{model_id}/weights.onnx | metadata.json | metrics.json
```
Media is served to the browser through short-lived signed URLs, never public paths.

## 4. Detection pipeline

1. Camera streams RTSP to Frigate's go2rtc.
2. Frigate runs motion detection on the sub-stream and runs the object detector only where motion exists.
3. Frigate tracks objects and publishes updates (label, score, zones entered, box) to MQTT.
4. The backend ingestor normalises each message into an observation `(camera, zone, class, track_id, score, ts)`.
5. The rule engine updates per-rule state in Valkey. When a condition has held for `duration_seconds` and the rule is outside cooldown and inside its schedule, it raises an event.
6. The event is stored in PostgreSQL. In `shadow` mode nothing is sent; this supports the 7-day shadow period in the onboarding process.
7. The worker fetches the snapshot and clip, delivers alerts, and queues actions (subject to the approval policy).
8. The event is pushed to dashboards over WebSocket and published on `visionguard/events/new`.
9. An operator reviews it. Feedback is stored per model and feeds the next training cycle.

Target latency: event → dashboard under 5 s, event → Telegram under 10 s.

## 5. Event persistence rule

Never alert on a single detection.

```text
Rule:        After-hours intrusion
Condition:   presence, class=person, zone=restricted_area
Confidence:  >= 0.65
Duration:    condition holds 5 s (time-based, independent of camera fps)
Schedule:    outside site business hours
Cooldown:    60 s per rule + camera
Severity:    high
Mode:        shadow for 7 days, then live
Actions:     Telegram + email + clip
```

Duration is time-based rather than frame-based, so rules behave the same on 5 fps and 10 fps cameras.

## 6. Model management and licensing

- Model files: `models/{model_id}/weights.onnx` (+ `metadata.json`, `metrics.json`).
- Model status: `training → testing → approved → archived` (or `failed`).
- "Active" is a **per-camera assignment** (`model_assignments`). The database enforces exactly one active model per camera. Rollback reactivates the previous assignment.
- Every model records its `architecture` and `license`. Activation for a paying customer is blocked for AGPL/non-commercial licences unless the platform holds the matching commercial licence.

| Model family | Licence | Commercial use |
|---|---|---|
| RF-DETR N/S/M/L (Roboflow) | Apache-2.0 | Yes (default choice for custom models) |
| Frigate's bundled SSDLite MobileNet | Apache-2.0 | Yes (default general detector) |
| YOLOX, D-FINE | Apache-2.0 | Yes |
| Ultralytics YOLOv8 / YOLO11 / YOLO26 | AGPL-3.0 or Enterprise | Only with an Enterprise licence or if the whole platform is open-sourced under AGPL |

## 7. Deployment environments

| Environment | Purpose | Hardware |
|---|---|---|
| Local development | Coding and testing | Laptop. Run `core` profile only, 1 camera or a video file |
| Pilot | First customer | Mini PC (Intel N100 class with iGPU for OpenVINO) or 4 vCPU/8 GB VPS |
| Production | Paying customers | 8 vCPU/16 GB RAM, Intel iGPU or NVIDIA GPU |
| Edge | Customer site | Mini PC, industrial PC, or Jetson |

## 8. Ports

| Service | Container port | Host port (default bind 127.0.0.1) |
|---|---|---|
| Backend API | 8000 | 8100 (8000 on the host is reserved for Coolify) |
| Dashboard (Streamlit) | 8501 | 8501 |
| Frigate UI (authenticated) | 8971 | 8971 |
| go2rtc RTSP / WebRTC | 8554 / 8555 | 8554 / 8555 |
| MQTT | 1883 | 1883 |
| Label Studio (profile `labeling`) | 8080 | 8080 |
| Node-RED (profile `automation`) | 1880 | 1880 |
| PostgreSQL, Valkey | 5432, 6379 | not published |

## 9. Scalability plan
- One Frigate instance per site for low-latency local processing.
- Use sub-streams and 5 fps for people; 10 fps only where fast objects matter (ball).
- Move heavy training to Colab or a GPU server.
- Multiple sites report to one central backend over MQTT/HTTPS.
