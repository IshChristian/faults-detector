# 90-Day Development Roadmap

## Days 1–7: Foundation
- Create GitHub repository.
- Install Python, Docker, VS Code, PostgreSQL tools.
- Create FastAPI project skeleton.
- Create Streamlit dashboard skeleton.
- Add user authentication.
- Run a detector (Frigate's SSDLite via OpenVINO) on a webcam, phone stream or recorded video file.

Deliverable: live webcam window with person detection.

## Days 8–14: Camera platform
- Deploy Frigate with Docker.
- Connect one RTSP camera or phone stream.
- Configure motion detection and snapshots.
- Publish Frigate events to MQTT.
- Save events to PostgreSQL.
- Build event list page.

Deliverable: camera events visible in dashboard.

## Days 15–21: Rules and alerts
- Add zone creation.
- Add rules engine.
- Add persistence and cooldown.
- Add Telegram alerts.
- Add email alerts.
- Add event snapshot/clip storage (local volume behind a storage interface; S3-compatible later).

Deliverable: “person in restricted zone” alert works end to end.

## Days 22–30: Training workflow
- Add dataset upload.
- Integrate Label Studio.
- Export YOLO dataset.
- Start an RF-DETR training job (Colab runner).
- Store the trained model (ONNX) in object storage with its licence and metrics.
- Activate model from dashboard.

Deliverable: custom model trained and deployed from dashboard.

## Days 31–45: Sports module
- Record local football/training footage.
- Label player, referee, goalkeeper, and ball.
- Train sports detection model.
- Use Frigate's tracker (or ByteTrack in the vision worker for the custom model).
- Add pitch zones.
- Add pitch-invasion and abandoned-object rules.

Deliverable: football demo with tracking and alerts.

## Days 46–60: Restaurant module
- Add queue-zone counting.
- Add table occupancy logic.
- Add kitchen safety rules.
- Add occupancy heatmap.
- Add daily operational report.

Deliverable: restaurant pilot dashboard.

## Days 61–75: Screen and equipment monitoring
- Add screen capture service.
- Add OCR error detection.
- Add frozen/black-screen detection.
- Add custom leak/smoke/PPE model.
- Add webhook actions.

Deliverable: screen and equipment fault alerts.

## Days 76–90: Production launch
- Deploy Coolify on Ubuntu server.
- Configure HTTPS and backups; test a restore.
- Complete NCSA data-controller/processor registration and customer DPAs.
- Add user roles and audit logs.
- Run pilot with 2–3 customers.
- Fix false positives.
- Prepare sales proposal and pricing.
- Onboard first paying customer.

Deliverable: production-ready platform and first subscription.
