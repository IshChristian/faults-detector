# AI Fault Detector — Project Documentation Pack

This pack contains the documents needed to start building, deploying, selling, and operating the **AI Fault Detector Platform**.

## Product name
**VisionGuard AI** — a self-hosted AI platform that monitors live CCTV, phone cameras, computer screens, and movement to detect faults, risks, and operational problems.

## Core use cases
- Football and sports: player/ball tracking, pitch intrusion, crowd safety, training analytics.
- Restaurants: queue length, table status, kitchen safety, after-hours entry, staff presence.
- Shops and venues: occupancy, loitering, restricted zones, incident evidence.
- Factories: leaks, smoke, stopped equipment, PPE, abnormal motion.
- Screens: frozen dashboards, error dialogs, black screens, unauthorized applications.

## Documents
1. `01-project-charter.md` — goals, scope, stakeholders, success metrics.
2. `02-product-requirements.md` — features, user stories, priorities.
3. `03-technical-architecture.md` — system design and data flow.
4. `04-database-schema.sql` — PostgreSQL database design (link to `database/init/01_schema.sql`).
5. `05-api-specification.md` — backend API endpoints.
6. `06-docker-compose.yml` — full local/server deployment stack (link to `docker-compose.yml`).
7. `07-frigate-config.yml` — CCTV ingestion and detection configuration (link to `frigate/config.yml`).
8. `08-rules-and-actions.md` — detection rules, alerts, and automated decisions.
9. `09-development-roadmap.md` — 90-day build plan.
10. `10-testing-and-acceptance.md` — test cases and go-live criteria.
11. `11-security-privacy-policy.md` — access, retention, and privacy controls.
12. `12-business-and-revenue-plan.md` — pricing, revenue targets, sales materials.
13. `13-installation-guide.md` — step-by-step server installation.
14. `14-model-training-guide.md` — dataset, labeling, training, deployment.
15. `15-sales-proposal-template.md` — customer proposal and contract terms.
16. `16-ui-ux-design-document.pdf` — visual design system, screens, components, tokens.

Runtime files: `docker-compose.yml`, `.env.example`, `frigate/config.yml`, `mosquitto/config/`, `database/init/`.
Files 04, 06 and 07 are symbolic links to the runtime files, so the docs and the deployed configuration can't drift apart.

## Technology decisions
- Backend: Python, FastAPI, with a background worker.
- Dashboard: Streamlit for MVP; React + Vite later, following the UI/UX design document.
- Cameras and detection: Frigate NVR 0.17 (go2rtc, OpenVINO detector), RTSP/ONVIF, USB and phone-camera streams.
- AI models: Apache-2.0 detectors (RF-DETR, Frigate's SSDLite) served with ONNX Runtime/OpenVINO; OpenCV.
  Ultralytics YOLO is AGPL-3.0 and is used only for experiments unless an Enterprise licence is bought.
- Rules: evaluated only in the VisionGuard backend. Node-RED is optional, for customer-specific integrations.
- Messaging: MQTT (Mosquitto, per-client users and ACLs). Queue/state: Valkey.
- Data: PostgreSQL 16; media on a local volume (MVP) or any S3-compatible store. MinIO was dropped because it no longer ships community images.
- Deployment: Docker Compose (pinned images, profiles) and Coolify on Ubuntu.
- Alerts: Telegram, email, webhook; siren/PLC only with approval or explicit pre-authorisation.

## Budget decision
Development software cost: **0 RWF**.  
Initial hardware budget: **up to 50,000 RWF**, preferably for a used 1080p USB webcam, phone mount, and 64 GB storage.

## Revision log
- **2026-11-07, documentation review.** Fixed: MQTT broker couldn't start (no password file) and Frigate had no MQTT credentials. Frigate zone coordinates exceeded the frame size (now relative). Port clashes with Coolify (8000) and Streamlit (8501). Compose exposed internal services with hard-coded passwords and `:latest` images. Missing `.env.example` and a `docker-compose.yml` name `docker compose` can find. Schema: wrong table order and missing foreign keys, no tenant scoping, no audit log, unenforced "one active model per camera", no count/dwell rule support, no shadow mode, no response-time fields. API roles mismatched the schema; missing CRUD, pagination, errors and WebSocket. Rules were evaluated in both Node-RED and the backend. MinIO replaced. Model licensing (AGPL) addressed. Rwanda Law 058/2021 obligations added. Leftover citation tags removed.

## First milestone
Within 30 days, deliver one live camera with YOLO person detection, event clips, Telegram alerts, dashboard, and one custom fault rule.
