# Testing and Acceptance Plan

## 1. Unit tests
Test:
- Zone polygon point-in-polygon logic.
- Rule condition types: presence, count, dwell, absence, line_cross, screen.
- Duration (time-based) persistence and schedule windows across timezone/midnight boundaries.
- Shadow mode records events but sends no alerts.
- Confidence threshold logic.
- Cooldown logic.
- Alert formatting.
- Model upload and activation.
- JWT authentication, refresh-token rotation and role permissions.
- Tenant isolation: a user can never read or modify another customer's data (404).
- One active model per camera; rollback; licence check blocks AGPL activation.
- Idempotent ingestion of duplicate Frigate MQTT messages.

## 2. Integration tests
Test:
- RTSP camera connects.
- Frigate publishes MQTT event.
- Backend stores event.
- Object storage receives snapshot/clip; signed URLs expire.
- Telegram alert is delivered; failed deliveries retry with backoff.
- Dashboard displays event.
- Operator review updates event status.

## 3. Model tests
For each custom model, measure:
- Precision.
- Recall.
- mAP@0.5.
- False positives per hour.
- Missed faults per 100 events.
- Inference latency.

Minimum launch target:
- Precision: 80% or higher.
- Recall: 75% or higher.
- False alarms: fewer than 5 per camera per hour during pilot.

## 4. Field test scenarios

### Football
- Person walks onto pitch.
- Object left on pitch.
- Crowd gathers near goal.
- Player falls and remains down.
- Ball leaves pitch.

### Restaurant
- Five or more people join queue.
- Customer sits at table.
- Staff enters kitchen without PPE.
- Smoke appears in kitchen.
- Person enters after closing time.

### Screens
- Dashboard is minimized.
- Error popup appears.
- Screen goes black.
- Dashboard freezes.

### Security
- Person enters restricted zone.
- Person loiters for five minutes.
- Motion occurs after business hours.

## 5. Performance tests
- One camera at 640x360, 5 FPS.
- Four cameras simultaneously.
- Dashboard with 10 open browser tabs.
- Telegram alert under poor internet.
- Server restart recovery (rule state and pending alerts survive).
- MQTT broker restart (backend reconnects and resubscribes).
- Disk-full behavior.

## 6. Go-live checklist
- [ ] Cameras online and stable for 24 hours.
- [ ] AI detection running without memory leak.
- [ ] Rules tested with real footage.
- [ ] Alerts received on Telegram/email.
- [ ] Clips saved and playable.
- [ ] Dashboard accessible through HTTPS.
- [ ] Backups configured.
- [ ] User roles tested.
- [ ] Customer staff trained.
- [ ] Pilot accuracy reviewed.
- [ ] Support contact and escalation process documented.
