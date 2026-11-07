# Product Requirements Document — VisionGuard AI

## 1. Product vision
One platform where a customer can connect cameras or screens, train custom fault models, monitor live operations, receive alerts, and trigger actions.

## 2. Users
| User | Needs |
|---|---|
| Super admin | Manage customers, servers, models, global settings |
| Customer admin | Manage cameras, zones, users, alert channels |
| Operator | View live feeds, review alerts, mark false positives |
| Analyst | View reports, heatmaps, trends, model performance |
| Integrator | Configure webhooks, PLC, POS, and third-party systems |

## 3. Functional requirements

### P0 — Must have
- User login with roles: super_admin, customer_admin, operator, viewer.
- Add camera by RTSP URL or USB device.
- Live camera dashboard.
- YOLO object detection.
- Person/object tracking.
- Define rectangular or polygon zones.
- Create rules based on object, zone, count, dwell time, duration, schedule, and confidence.
- Shadow mode for new rules (record events without alerting).
- Save event snapshot and short clip.
- Telegram and email alerts.
- Event list with filters and status.
- Acknowledge, resolve, and mark false-positive events.
- Store model versions and activate one model per camera, with rollback.
- Audit log of logins, reviews, exports, configuration changes and actions.
- Docker Compose deployment.

### P1 — Should have
- Screen-capture monitoring and OCR.
- Football module: player, referee, goalkeeper, ball detection and tracking.
- Restaurant module: queue count, table occupancy, kitchen zone monitoring.
- Label Studio integration.
- Training-job status and metrics.
- Daily/weekly PDF or web reports.
- Webhook actions.
- Node-RED integrations (consume VisionGuard events; rules stay in the backend).

### P2 — Could have
- PLC/MES machine-stop integration.
- POS integration.
- Face blurring.
- Mobile PWA dashboard.
- Multi-tenant customer management.
- Heatmaps and dwell-time analytics.
- Voice announcements.

## 4. User stories
1. As a restaurant manager, I want to know when more than five people are waiting, so I can open another counter.
2. As a security officer, I want an alert when someone enters a restricted zone after hours.
3. As a football academy coach, I want player and ball tracking so I can review training sessions.
4. As a factory supervisor, I want an alert when smoke or a leak is detected near equipment.
5. As an IT operator, I want an alert when a dashboard becomes blank or displays an error.
6. As an admin, I want to train a new fault class without leaving the dashboard.
7. As an operator, I want to mark false alarms so the system improves.

## 5. Non-functional requirements
| Requirement | Target |
|---|---|
| Detection latency | Under 5 seconds |
| Alert delivery | Under 10 seconds |
| Dashboard refresh | 1–5 seconds |
| Camera stream | 640x360 to 1280x720 for AI |
| Event clip length | 5–15 seconds |
| Data retention | Configurable, default 14 days |
| Concurrent users | 10 on initial deployment |
| Availability | 99% |
| Deployment | Docker Compose on Ubuntu |

## 6. Acceptance criteria
- A camera can be added and display live video.
- A person entering a defined zone produces an event after the configured duration.
- The event appears in the dashboard and Telegram within 10 seconds.
- A trained model can be uploaded, activated, and used by a camera.
- An operator can mark an event as false positive.
- The entire system can be redeployed from a Git repository using Docker Compose/Coolify.
