# VisionGuard AI — V1 Design: one platform, live + upload modes

Date: 2026-11-07 · Status: draft for approval (builder check done) · Owner: IshChristian

This document defines V1 of VisionGuard AI. It builds on the documentation pack in the repo root (00–16), which describes the long-term platform. Where this document and the pack disagree, **this document wins for V1**. Decisions marked *(builder's call)* or *(Claude's call)* were not explicitly made by the owner and may be revisited.

---

## 1. Intent

VisionGuard is **one platform** that turns video into decisions. V1 proves it in two markets at once, using one shared core:

- **Upload mode** for **football academies**. Coaches film training, upload the video, and the next morning review an analysed session: player tracking, teams, a bird's-eye mini-map, heatmaps, intensity, drills, tagged moments and shareable clips. *First pilot: a football academy whose coaches review training sessions.*
- **Live mode** for **CCTV customers** (restaurants, shops, security, schools). Any number of cameras chosen by the customer feed Frigate. VisionGuard turns Frigate's detections into business rules, incidents and Telegram alerts with evidence clips. *Second pilot: a restaurant, shop or security site using standard rules (owner agreed to this assumption).*

**Why both at once:** the owner wants to attack several markets simultaneously. The two modes share ~70% of the work (detection, tracking, zones, storage, clips, review UI, users), so the second mode is cheaper than a second product.

**Why Frigate:** customers decide how many CCTV cameras to connect, possibly dozens. Frigate already handles multi-camera ingestion, hardware acceleration, motion-gated detection, recording and restreaming. VisionGuard does not rebuild that.

## 2. Goals, non-goals, anti-goals

### Goals (V1)
1. A coach can go from "video on a phone" to "analysed session ready to review" without help from us.
2. The review screen makes finding and sharing a moment take under a minute.
3. A CCTV customer can connect cameras through Frigate, define zones and rules in VisionGuard, and get a Telegram alert with a snapshot and clip within 10 s of the rule firing.
4. Rules start in shadow mode, so a pilot can see what *would* have alerted before alerts go live.
5. Everything runs self-hosted on modest hardware: the developer's laptop for development, a mini PC for pilots.
6. No custom model training is needed to launch either pilot. Pretrained Apache-2.0 models only.

### Non-goals (V1)
- Live football analytics (stats during a match).
- Automatic, reliable identification of *which* player a track is for a whole session. The coach confirms bib numbers.
- Pass, possession and shot statistics.
- Custom fault models (smoke, PPE, leak), the training studio UI, auto-labelling, the retraining loop.
- AI second opinion (vision-language model), sensors, WhatsApp/SMS, escalation chains, edge/central console, reseller portal, billing. All of these are V2+.
- Screen monitoring.
- Node-RED and Label Studio. They stay optional in compose, but V1 code does not depend on them.

### Anti-goals (failure even if it technically works)
- **Coaches don't trust the numbers.** Showing precise-looking stats that are wrong is worse than showing fewer stats. Approximate metrics must be labelled as approximate, and anything below a quality bar is hidden rather than shown.
- **Alert fatigue.** A live pilot that sends noisy alerts gets switched off. Shadow mode, durations and cooldowns are mandatory parts of the flow, not options.
- **Privacy failure with minors.** Academy players are mostly children. No face recognition, no public links that never expire, no processing abroad.
- **Two products glued together.** Live and upload must share one data model, one UI and one set of users. A customer with both should see one platform.

## 3. Constraints

| Constraint | Consequence |
|---|---|
| Solo developer, ~9–11 weeks to pilot-ready | Strict V1 scope; milestones in §10 |
| Dev laptop: 4 cores, 3.7 GB RAM, no GPU, no Docker yet | Docker install is step 1. Dev runs the core profile with 1 test camera. Upload processing runs on CPU, so it must work overnight-slow |
| Hardware budget 50,000 RWF | Upload mode: old phone + tall tripod/pole + power bank. Live pilot: customer's existing CCTV and a server (mini PC recommended, customer-funded) |
| Model licensing | Apache-2.0 / MIT only for anything deployed (RF-DETR, Frigate's bundled SSDLite, ByteTrack via `supervision`). No Ultralytics in shipped code |
| Rwanda Law 058/2021 | Personal data processed and stored in Rwanda. **Upload-mode processing must not go to Colab or any foreign cloud.** Parental consent for academy players |
| Internet is unreliable | Nothing in the critical path requires internet except outbound alert delivery, which retries |
| Existing docs pack | Reuse schema, API conventions, compose, Frigate config and security policy; extend rather than replace |

## 4. Architecture

```
 LIVE MODE                                          UPLOAD MODE
 CCTV cameras (any number)                          Phone video file(s)
        |  RTSP                                            | resumable upload (LAN/Wi-Fi)
 +------v------------------+                       +-------v------------------+
 | Frigate 0.17            |                       | Session processor        |
 | go2rtc, detect, track,  |                       | (worker job)             |
 | record, snapshots       |                       | transcode → detect →     |
 +------+------------------+                       | track → teams → project  |
        | MQTT frigate/events                      | → metrics                |
 +------v------------------+                       +-------+------------------+
 | Ingestor + Rule engine  |                               |
 | (backend)               |                               |
 +------+------------------+                               |
        |                                                  |
 +------v--------------------------------------------------v------+
 |                    Shared core (FastAPI + worker)               |
 | tenancy · users/roles · sites · sources · zones · events/       |
 | incidents · media storage · clips · share links · audit log     |
 +------+------------------------------------------+---------------+
        |                                          |
 PostgreSQL · Valkey · media volume         Telegram (alerts + ack buttons)
        |
 React dashboard (Live Operations · Fault Center · Sessions · Cameras · Settings)
```

### Services (docker compose, `core` profile)
`backend` (FastAPI API + WebSocket), `worker` (jobs: session processing, alert delivery, clip export, retention, Telegram bot polling), `dashboard` (React static build behind a small web server), `frigate`, `mqtt`, `postgres`, `valkey`. Compose, `.env.example`, the Mosquitto config and the Frigate config already exist in the repo and are the starting point.

The worker must be able to run **session processing in a separate queue** with concurrency 1, so a long session job never delays alert delivery. *(Claude's call.)*

### Tech choices
| Area | Choice | Note |
|---|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 (async), Alembic | Alembic owns migrations from day one; `database/init/01_schema.sql` becomes the first migration |
| Jobs | Valkey-backed queue (e.g. `arq` or `rq`) | *Builder's call which library* |
| Video | ffmpeg (CLI), PyAV/OpenCV for frame reading | |
| Detection | RF-DETR Nano (Apache-2.0), COCO-pretrained, ONNX Runtime CPU (OpenVINO EP where available) | Classes used: `person`, `sports ball` |
| Tracking | ByteTrack via `supervision` (MIT) | |
| Live detection | Frigate's bundled SSDLite via OpenVINO (as in `frigate/config.yml`) | |
| Dashboard | **React + Vite + TypeScript** *(Claude's call: synced video, overlays and timeline aren't practical in Streamlit; the UI/UX doc already targets React)* | Follows `16-ui-ux-design-document.pdf` tokens and layout |
| Charts | Any lightweight React chart lib | *Builder's call* |
| Auth | JWT access + rotating refresh tokens, argon2id | As in `05-api-specification.md` |

### Deployment topology (owner's decision)
- **One box per customer site.** Each pilot customer gets its own mini PC on their premises (Intel N100-class with iGPU or better, 16 GB RAM, 512 GB+ SSD; this is "the target pilot machine" for every performance target here). It runs the full compose stack for that one customer. Customers never share a server.
- **Tenancy in V1:** one customer per install. The code still scopes every query by `customer_id` (cheap, and it keeps the path open to a central console in V3), but row-level security and cross-tenant hardening are not V1 requirements.
- **Uploads** go over the site's local Wi-Fi/LAN directly to the box.
- **Remote access** (coaches reviewing from home, share links for players/parents, Telegram links for operators) goes through a **relay**: a small Rwanda-hosted VPS that the box connects to outbound over WireGuard. The VPS forwards HTTPS **without terminating TLS** (TLS passthrough by SNI), so it never sees footage in plaintext and the box needs no open inbound ports. Certificates are issued on the box. One relay VPS can serve all customer boxes, each on its own subdomain. *(Claude's call on the mechanism; specific tools are the builder's call. Avoid tunnel services that terminate TLS outside Rwanda.)*
- Exposed through the relay: the dashboard/API only (login required) and the public share-link player route. Frigate, MQTT, PostgreSQL and Valkey are never exposed.
- Hardening for exposure (rate limiting, login lockout, security headers, keeping dependencies patched) is part of M5.
- The developer laptop runs the same stack for development with 1 looped test camera.

## 5. Shared core

### Tenancy and roles
As in the schema: `customers → sites → sources`, every row scoped by `customer_id`. Roles stay `super_admin`, `customer_admin`, `operator`, `viewer`. The UI labels `operator` as **"Coach"** for sports customers. *(Claude's call: no new role is needed for V1.)*

### Sources
The existing `cameras` table gains a mode: `live` (Frigate camera, `frigate_name` required) or `upload` (a pitch/recording position, holding the pitch calibration). Source types stay as in the schema. *Exact column design is the builder's call.*

### Events and incidents
- **Event:** one rule firing (live) or one coach tag / auto-detected moment (upload). The existing `events` table is used for live; upload moments use `session_tags` (§7).
- **Incident (live only in V1):** what the operator reviews and what Telegram buttons act on. Status `open → acknowledged → resolved | false_positive`, with `acknowledged_by` and time-to-acknowledge. *(Claude's call: a thin `incidents` table referencing events. Escalation chains are V2.)*
- **Cooldown and grouping semantics** *(Claude's call; this replaces the cooldown wording in `08-rules-and-actions.md`, which must be updated to match):*
  - The rule engine keeps evaluating during cooldown. Cooldown only suppresses **notifications**, never recording.
  - When a rule fires and the (rule, camera) pair has an incident that is not resolved and whose last event is within `cooldown_seconds`, the new event **attaches to that incident**. The window slides: each attached event extends it. Otherwise a new incident opens and an alert is sent.
  - A condition that holds continuously (someone loitering for an hour) is **one event** that stays open until the condition ends (`ended_at`), so it is one incident, not 60.
  - Attaching to an `open` or `acknowledged` incident does **not** re-alert, unless the new event's severity is higher than the incident's (e.g. count rose past a critical threshold).
  - An incident marked `false_positive` or `resolved` is closed. A later firing opens a new incident.
  - In shadow mode the same logic runs and incidents are recorded with `rule_mode = shadow`. The pilot report shows "alerts that would have been sent" = number of shadow incidents opened.

### Media storage
Local Docker volume behind a storage interface with `local` (V1) and `s3` (later) backends. Key layout as in `03-technical-architecture.md` §3, plus:
```
sessions/{customer_id}/{session_id}/source/{video_id}.mp4     original upload
sessions/{customer_id}/{session_id}/proxy/{video_id}.mp4      720p H.264 proxy for playback
sessions/{customer_id}/{session_id}/analysis/tracks.parquet   per-frame track points
sessions/{customer_id}/{session_id}/analysis/summary.json     aggregates for the UI
clips/{customer_id}/{yyyy}/{mm}/{clip_id}.mp4
```
**Per-frame track data does not go in PostgreSQL.** A 90-minute session at 10 fps with ~25 people is ~1.3M points. Store it in Parquet. PostgreSQL holds sessions, aggregates, tags, clips and players. *(Claude's call.)*

### Clips and share links
- Any user with operator+ role can cut a clip (in/out points) from a session video or a live incident. ffmpeg cuts from the proxy (upload mode) or Frigate's recording (live mode).
- A share link is a random token URL that plays only that clip, **expires after 7 days by default (configurable, max 30)**, can be revoked, and logs every view in the audit log. No login needed to view, so players and parents can open it on a phone. *(Claude's call, balancing ease against the minors anti-goal.)*

### Audit
Logins, reviews, exports, share-link creation and views, rule changes and calibration changes go to `audit_logs`.

## 6. Live mode

### Frigate integration
- Cameras are configured in `frigate/config.yml` (as in the repo). V1 does not generate Frigate config from the UI; the admin edits the file and VisionGuard maps cameras by `frigate_name`. *(Claude's call. UI-driven Frigate config is V2.)*
- The backend subscribes to `frigate/events` (MQTT user `visionguard_backend`) and normalises each message into an **observation**: `(camera, frigate_event_id, label, score, box, current_zones, timestamp)`.
- Zones: V1 zones are **Frigate zones**, drawn in Frigate's UI and mirrored into VisionGuard by name, with the polygon copied for display. Rules reference VisionGuard zone records.
- Camera health: a camera is `offline` when Frigate's stats API (`/api/stats`, polled every 30 s by the worker) reports camera fps 0 or the camera missing. Going offline or recovering raises a `camera_health` event. *Covered/blurred detection is V2.*
- Dev without CCTV: a go2rtc stream sourced from a looping local video file stands in for a camera.

### Rule engine (V1 condition types)
Implemented: `presence`, `count`, `dwell`, plus schedules (`always`, `business_hours`, `outside_business_hours`, explicit windows in site timezone) and cooldowns. `absence`, `line_cross` and `screen` are in the schema but not implemented in V1.

- State per (rule, camera) lives in Valkey and survives restarts.
- Duration is time-based.
- `count` counts distinct Frigate tracked objects currently in the zone with score ≥ threshold.
- `dwell` uses the time a single `frigate_event_id` has been in the zone.
- Shadow vs live is per rule; new rules start in shadow.

### V1 rule templates (live)
After-hours intrusion (presence, outside business hours) · Restricted-zone entry (presence) · Loitering (dwell > N s) · Queue too long (count > N for T s) · Occupancy limit (count > N) · Camera offline (health).

### Alerts
- **Telegram** via a bot. The worker uses **long polling** (`getUpdates`), so no inbound webhook is needed. **No footage is sent to Telegram (owner's decision: data localisation).** Each alert is text only: rule, camera, site, time, severity, plus inline buttons **Acknowledge** and **False alarm** that update the incident, and a **View evidence** link to the incident page on the dashboard (via the relay; login required, and the session is remembered on the operator's phone). The snapshot and clip are shown there.
- Recipients: users with a `telegram_chat_id` on that customer whose role is in the rule's `notify` list. A user links their chat by sending `/start <one-time code>` shown in the dashboard. *(Claude's call.)*
- **Email** as a secondary channel (SMTP), also text + link only, no attachments.
- Retries per `08-rules-and-actions.md` §7. Webhook/siren/PLC are out of V1.
- The worker copies the snapshot and clip from Frigate's API (for the `frigate_event_id`) into VisionGuard storage, so evidence outlives Frigate's own retention. Pre-roll 5 s, post-roll 10 s.

## 7. Upload mode (football academy)

### Recording guidance (shipped as a one-page guide in the app)
Phone on a 3–4 m pole/tripod or elevated position, at the halfway line on one side, landscape, whole pitch in frame, 1080p, 25–30 fps, locked exposure if possible, power bank. Same position every session where possible, so calibration can be reused.

### Session lifecycle
1. **Create session:** site, pitch (source), date and time, type (training/match), optional title and squad.
2. **Upload:** one or more video files (phones split long recordings). **Resumable chunked upload** (tus protocol or equivalent) so a dropped Wi-Fi connection doesn't restart a multi-GB file. Accept up to 10 GB per file. Files are ordered by their `creation_time` metadata, with manual reorder available.
3. **Calibrate:** on the first frame, the coach clicks 4 pitch reference points (the corners of the visible pitch, or other marked points from a picker) and enters the pitch dimensions (default 100×64 m; academies often use smaller pitches). This gives a homography to pitch coordinates. If the source already has a calibration from the same position, offer to reuse it. **Analysis may start before calibration.** Projection-dependent metrics are computed when calibration is saved, and recomputed if it's edited.
4. **Process (worker job):**
   1. Transcode to a 720p H.264 proxy for **playback**. Analysis reads the **original** file, at full resolution where needed (tiled inference on the far half of the frame is the fallback for distant players).
   2. Sample at 10 fps. *(Claude's call; builder may tune.)*
   3. Detect `person` and `sports ball` with RF-DETR Nano.
   4. Track with ByteTrack.
   5. **Team assignment:** colour features from the torso region of each track, clustered into 2 teams plus an "other" bucket (goalkeepers, coaches, referees, spectators). Done per track, not per frame. The coach can correct a track's team in the UI, and corrections persist.
   6. **Pitch filter:** after calibration, drop tracks whose projected foot point is mostly outside the pitch (spectators, people walking past).
   7. **Ball:** detect and track best-effort. Shown in the UI only where detected; no ball-derived stats in V1.
   8. **Metrics (after calibration):** per track and per team. Distance, top speed, time in speed bands, sprint count (threshold configurable per squad, default 19 km/h; youth squads need lower), heatmap, average position. Team width, depth and compactness over time. **Intensity timeline:** mean player speed per 10 s window.
   9. Write `tracks.parquet` and `summary.json`. Report progress (% of frames) to the UI.
5. **Review** (§7, review screen).
6. **Retention:** originals are kept until analysis succeeds, then for a further **14 days** (configurable) so sessions can be reprocessed after a bug fix or better model, then deleted. Disk use is shown on the Settings page. *(Claude's call.)* Proxy and analysis are kept per the customer's retention setting (default 90 days for sessions, distinct from the 14-day live-clip default). Clips are kept until deleted.

### Coach tagging
- A mobile web page (part of the dashboard, phone-friendly, works on a weak connection and queues offline) with large buttons: configurable tag types (default: *Drill start*, *Drill end*, *Good*, *Mistake*, *Review*) and an optional player number.
- Each tap records **wall-clock time** on the coach's phone.
- Alignment: tags are mapped onto the video using the video file's `creation_time` metadata. The review screen has a **sync offset control** (drag ± seconds, with a preview) because phone clocks and metadata drift. The offset is saved per session. *(Claude's call.)*
- Tags can also be added afterwards on the review timeline.

### Drills
Drill segments come from *Drill start/end* tags. The UI also suggests segment boundaries where the intensity timeline shows a sustained change, as suggestions the coach accepts or rejects. Every metric can be filtered to a drill.

### Player identity
Tracks fragment when players cross or leave the frame. V1 does **not** promise automatic identity. Instead:
- The coach can assign a **bib number / player name** to a track from the review screen, and **merge** track fragments of the same player (select tracks → merge).
- Per-player stats appear only for players the coach has labelled. Team-level stats need no labelling.
- A squad roster (name, bib number, position) is stored per site, with **no photos**.
- **Consent** *(Claude's call)*: each roster player has `consent_status` (`granted|missing|withdrawn`), recorded by the academy from the paper form. V1 doesn't block anything automatically, because unlabelled people (opponents, spectators) can't be identified without face recognition. Instead: (a) players with `missing`/`withdrawn` consent can't be labelled on tracks, so no per-player stats or named overlays exist for them; (b) the clip-share dialog warns when the clip's time range contains tracks labelled with non-granted consent; (c) share links can only be created by `customer_admin`/`operator`. Face blurring of exported clips is V2.

### Quality gates (anti-goal: untrustworthy numbers)
- A session shows a **data quality** indicator: fraction of frames with ≥ N players tracked, calibration present, mean track length.
- Distance and speed are shown as approximate ("≈"). Per-player distance is hidden for players whose labelled tracks cover < 60% of the drill/session. *Thresholds tunable by the builder after the pilot benchmark.*
- Speeds above a physical cap (e.g. 36 km/h) are treated as tracking errors and smoothed out.

### Review screen
Layout following the UI/UX doc:
- **Video player** (proxy) with toggleable overlays: boxes in team colours, track IDs or player names, ball marker.
- **Mini-map** (bird's-eye pitch) synced to the playhead, showing dots per player in team colours.
- **Timeline** under the video: intensity curve, drill segments, tag markers. Click to seek.
- **Side panel tabs:** *Tags* (list, filter, jump) · *Drills* · *Team stats* (heatmaps, width/compactness, distance by team) · *Players* (labelled players' stats, heatmap per player).
- **Clip** button: set in/out, title, then save and optionally create a share link.
- Keyboard shortcuts for play/pause, ±5 s, next/previous tag, and set in/out.

### Performance targets (upload)
- On the target pilot machine, a 90-minute 1080p session finishes processing within **8 hours** (overnight).
- On the developer laptop it must complete, however slowly.
- **Week 1 includes a benchmark spike** on real academy footage (or similar public footage) to confirm detection quality on distant players and CPU throughput. If distant players are missed, tiled inference on the far half of the frame is the first fallback. *(Claude's call; this is the biggest technical risk.)*

## 8. Data model changes (on top of `database/init/01_schema.sql`)

New tables, with exact columns left to the builder:
- `sessions` (customer, site, source, type, starts_at, title, status: `uploading|queued|processing|ready|failed`, sync_offset_ms, quality jsonb, summary_key)
- `session_videos` (session, order, original_key, proxy_key, duration, fps, resolution, creation_time, status)
- `calibrations` (source, image points, pitch points, pitch size, created_by). A session references the calibration used
- `session_tracks` (session, track_id, team: `a|b|other`, team_corrected bool, player_id nullable, merged_into nullable, frames_count, first/last ts, aggregate metrics jsonb)
- `players` (customer, site, name, bib_number, position, consent_status, active). No images
- `session_tags` (session, type, wall_clock_ts, video_ts_ms, player_id nullable, note, created_by, source: `live_tagger|review`)
- `drills` (session, name, start_ms, end_ms, source: `tags|suggested|manual`)
- `clips` (customer, source: session or incident, start_ms, end_ms, title, storage_key, created_by)
- `share_links` (clip, token_hash, expires_at, revoked_at, view_count)
- `incidents` (customer, rule, camera, status, opened_at, acknowledged_by/at, resolved_by/at). `events.incident_id` FK
- `jobs` view or table for processing progress if the queue library doesn't provide it

Changes: `cameras` gains `mode` (`live|upload`); `users.telegram_chat_id` already exists; add a one-time Telegram link code table or column.

## 9. Privacy and consent (V1 specifics)
- Academy onboarding includes a **parental consent form** template covering filming for coaching, storage location, retention, clip sharing, and no face recognition. The academy is the data controller, VisionGuard the processor (DPA per `11-security-privacy-policy.md` §7).
- All processing is local to the server at the academy, or the owner's machine in Rwanda. **No Colab or foreign cloud for customer footage.**
- No face recognition, no face crops stored, no player photos.
- Share links expire, can be revoked, and are logged.
- A customer admin can delete a session and all derived data in one action. The deletion is logged.

## 10. Milestones (~9–11 weeks)

| # | Weeks | Deliverable |
|---|---|---|
| M0 | 1 | Docker on laptop; repo scaffold (backend, worker, dashboard); Alembic baseline from existing schema; CI running tests; **benchmark spike** on football footage (detect + track on CPU) with a go/no-go note |
| M1 | 2–3 | Shared core: auth, tenancy, sites, sources, users, storage interface, audit log; React shell with sidebar/top bar per UI doc |
| M2 | 3–5 | Upload mode backend: resumable upload, transcode, detect/track, team assignment, calibration + projection, metrics, Parquet/summary, progress |
| M3 | 5–7 | Review screen: player + overlays, mini-map, timeline, tags, drills, stats tabs, track labelling/merge, clips + share links; mobile tagger page |
| M4 | 7–9 | Live mode: Frigate MQTT ingestion, zones mirror, rule engine (presence/count/dwell, schedules, cooldown, shadow), incidents, Telegram with buttons, email, Frigate snapshots/clips, camera health; Live Operations + Fault Center screens |
| M5 | 9–11 | Relay VPS + WireGuard + TLS passthrough; exposure hardening; retention jobs, backups, deletion, quality gates, install guide update, pilot runbooks (academy + live), acceptance tests on real footage; update docs 02/03/09/10/13 to match V1 |

The two pilots can start at the end of M3 (academy) and M4 (live).

## 11. Acceptance criteria (pilot-ready)

**Upload mode**
- A coach records a 60–90 min session per the guide, uploads it over Wi-Fi (surviving one forced disconnect), calibrates, and the session reaches `ready` within 8 h on the pilot machine.
- On a 10-minute hand-checked sample: ≥ 85% of on-pitch players detected in ≥ 80% of sampled frames; team assignment ≥ 90% correct per track-minute after zero corrections. *(Targets set by Claude; adjust after the M0 spike.)*
- Tags from the mobile tagger appear on the timeline within ±2 s after sync adjustment.
- A clip can be cut and shared, the link opens on a phone without login, and it stops working after expiry or revocation.
- Labelling and merging tracks updates per-player stats.

**Live mode**
- With ≥ 2 cameras in Frigate (one may be a looped file), a person entering a restricted zone after hours produces an incident in shadow mode (no alert) and, after switching to live, a text Telegram alert in ≤ 10 s. Its View evidence link opens the incident with the snapshot immediately and the clip within 30 s, from a phone outside the site network (via the relay).
- Acknowledge and False alarm buttons in Telegram update the incident in the dashboard.
- Count and dwell rules fire correctly at their thresholds and respect cooldowns. Rule state survives a backend restart.
- Unplugging a camera raises a camera-offline event within 60 s.

**Platform**
- Every API query is scoped by `customer_id` (tested). The box exposes no inbound ports; remote access works only through the relay; Frigate, MQTT, PostgreSQL and Valkey can't be reached from outside. Audit entries exist for login, review, clip share and rule change. `docker compose up` on a clean Ubuntu machine following the install guide reaches a working system.

## 12. Left to the builder
- Library choices where marked (job queue, chart library, tus server implementation, React component library within the UI/UX tokens).
- Exact table columns and indexes for the new tables, and API endpoint shapes, following `05-api-specification.md` conventions.
- Tuning: sample fps, tracker parameters, colour-clustering features, sprint thresholds, quality-gate thresholds, informed by the M0 benchmark.
- Test strategy details beyond §11 (unit tests for rule engine and metrics math are expected; TDD encouraged).
- Whether the dashboard is served by its own container or by the backend.

## 13. Calls made without explicit owner sign-off
Listed so the owner can check them:
1. React instead of Streamlit for the dashboard.
2. Frigate config edited by file in V1, not generated from the UI.
3. V1 rule types limited to presence/count/dwell plus camera health.
4. Telegram with long polling and Acknowledge/False alarm buttons; email secondary; no SMS/WhatsApp in V1.
5. Per-frame tracks in Parquet, not PostgreSQL.
6. Share links that need no login, expire after 7 days by default, and are revocable.
7. Originals kept 14 days after successful analysis (for reprocessing), then deleted; sessions retained 90 days by default. Analysis runs on originals, the proxy is for playback.
12. Cooldown/incident grouping semantics in §5 (supersedes doc 08 wording).
13. Consent tracked per roster player; no automatic blocking or blurring in V1 (§7).
8. Coach labels players manually (assign + merge); no automatic identity.
9. Tag alignment via video metadata plus a manual sync offset.
10. Upload-mode processing strictly local (no Colab), because of the data-localisation rule.
11. Second pilot assumed to be a restaurant, shop or security site (owner agreed).
