# Project Charter — VisionGuard AI

## 1. Purpose
Build a low-cost, self-hosted AI platform that detects faults and abnormal events from live CCTV cameras, phone cameras, computer screens, and movement data.

## 2. Problem
Businesses and sports venues already have cameras but cannot continuously watch every feed. Incidents such as queue buildup, intrusion, kitchen risks, pitch invasion, equipment leaks, and dashboard failures are often discovered too late.

## 3. Solution
VisionGuard AI analyzes live video and screen feeds locally, detects defined faults, saves evidence clips, sends alerts, and can trigger automated actions.

## 4. Objectives
- Detect events in near real time.
- Run on affordable local hardware or one VPS.
- Provide one dashboard for training, detection, alerts, actions, and reporting.
- Keep software licensing cost at zero using open-source tools.
- Reach 10 paying customers and 1,920,000 RWF monthly recurring revenue in year one.

## 5. Scope

### In scope
- Live RTSP/IP camera, USB camera, phone camera, and screen-capture ingestion.
- Object detection, tracking, zone rules, and event persistence.
- Football, restaurant, retail, security, and equipment monitoring modules.
- Model training, labeling integration, model versioning, and activation.
- Alerts via Telegram, email, webhook, dashboard, and optional PLC/API actions.
- Docker-based deployment with Coolify.

### Out of scope for version 1
- Fully autonomous security enforcement without human approval.
- Facial recognition.
- Guaranteed detection of every possible fault.
- Professional broadcast-quality multi-camera sports tracking.
- Cloud-only storage of continuous 24/7 video.

## 6. Stakeholders
| Role | Responsibility |
|---|---|
| Founder / developer | Build platform, deploy customers, train models |
| Customer admin | Configure sites, users, alert recipients |
| Operator | Review alerts, acknowledge or reject events |
| Security/maintenance team | Respond to alerts |
| Data subject | Person visible in camera footage |

## 7. Success metrics
| Metric | Target |
|---|---|
| Detection latency | Under 5 seconds from event to alert |
| False-positive reduction | At least 40% after feedback tuning |
| System uptime | 99% monthly |
| Camera capacity | 1–4 low-resolution cameras on initial server |
| First customer pilot | Within 45 days |
| Year-one customers | 10 active subscriptions |

## 8. Budget
- Software and model training: 0 RWF using open-source tools and free Colab.
- Initial hardware: up to 50,000 RWF.
- Recommended first hardware: used 1080p USB webcam, phone mount, 64 GB USB/SD storage.

## 9. Key risks
| Risk | Mitigation |
|---|---|
| False alarms | Require multi-frame persistence, confidence thresholds, human feedback |
| Poor camera angle | Perform site survey before installation |
| Limited GPU | Use small detectors (RF-DETR Nano, SSDLite) with OpenVINO, sub-streams at 5 fps, Colab for training |
| Model licensing | Deploy only Apache-2.0 models commercially; Ultralytics YOLO only with an Enterprise licence |
| Data-protection compliance | Register with NCSA, keep data in Rwanda, signage, retention limits (see `11-security-privacy-policy.md`) |
| Privacy concerns | Local processing, limited retention, role-based access, face blurring option |
| Customer expects perfect AI | Use pilot period, clear accuracy disclaimers, measurable KPIs |
