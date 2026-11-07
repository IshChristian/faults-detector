# Rules, Alerts, and Automated Decisions

## 1. Rule structure
Rules are evaluated **only by the VisionGuard backend**. Node-RED may react to events but never decides them.

Every rule has:

| Field | Meaning |
|---|---|
| Source | Camera, screen agent, or all cameras on a site |
| Zone | Optional polygon or line (relative coordinates) |
| Condition type | `presence`, `count`, `dwell`, `absence`, `line_cross`, `screen` |
| Object class | e.g. `person`, `sports ball`, `smoke` |
| Params | Condition-specific, e.g. `{"operator":">","threshold":5}` |
| Min confidence | 0–1 |
| Duration | Seconds the condition must hold continuously (time-based, not frames) |
| Cooldown | Seconds during which new firings of the same rule on the same camera attach to the open incident instead of sending a new alert (recording never stops; see V1 design §5) |
| Schedule | Always, business hours, outside business hours, or explicit windows |
| Severity | low / medium / high / critical |
| Mode | `shadow` (record only) or `live` (alerts and actions) |
| Actions | Notifications, clip, webhook, approved automations |

### Condition types
| Type | Fires when | Example params |
|---|---|---|
| `presence` | ≥1 matching object is in the zone for the duration | — |
| `count` | The number of matching objects in the zone satisfies the operator for the duration | `{"operator":">","threshold":5}` |
| `dwell` | A single tracked object stays in the zone longer than the duration | — (duration = dwell time) |
| `absence` | No matching object, or no motion, for the duration | `{"signal":"motion"}` or `{"signal":"object"}` |
| `line_cross` | A tracked object crosses a line zone | `{"direction":"in"}` |
| `screen` | A screen check holds for the duration | `{"check":"black","max_brightness":8}` · `{"check":"frozen"}` · `{"check":"ocr_match","patterns":["Error","Failed","Critical"]}` · `{"check":"unauthorized_app","allow":["chrome.exe","pos.exe"]}` |

### Rules that need extra capability
Some rules below depend on capabilities not yet in the platform. They are marked with the requirement and are **not** sold until it ships:
- **[custom model]**: needs a trained detector for that class (smoke, fire, leak, PPE, missing guard, dirty table).
- **[pose]**: needs a pose model (player down).
- **[sensor]**: needs a non-camera input (thermal camera, temperature sensor).

## 2. Sports rules

| Rule | Condition | Severity | Action |
|---|---|---|---|
| Pitch invasion | `presence` person in `pitch` during match schedule. Players and staff are excluded by a separate class or by roster count | High | Telegram + siren (approved) + clip |
| Goal-area crowding | `count` person in `goal_area` > 10 for 10 s | Medium | Alert steward |
| Abandoned object | `dwell` of a non-person object in `pitch` > 60 s **[custom model]** for generic objects | Medium | Alert security |
| Player down | Person low/horizontal with little motion for 10 s **[pose]** | High | Alert medical staff |
| Ball out of play | `absence` of `sports ball` in `pitch` for 5 s | Low | Log only |
| Crowd surge | `count` rate of change: +N people within T seconds (`{"operator":"rate>","threshold":15,"window_s":30}`) | High | Alert control room |

## 3. Restaurant rules

| Rule | Condition | Severity | Action |
|---|---|---|---|
| Long queue | `count` person in `queue_zone` > 5 for 120 s | Medium | Notify manager |
| Table needs cleaning | Table zone empty for 10 min after occupancy, and dirty-table class present **[custom model]** | Low | Notify waiter |
| Kitchen fire/smoke | `presence` smoke/fire ≥ 0.75 for 3 s **[custom model]** | Critical | All channels + siren; PLC/gas cut-off only if pre-authorised |
| Missing PPE | Person in `kitchen` without cap/gloves for 10 s **[custom model]** | Medium | Notify supervisor |
| After-hours entry | `presence` person, schedule outside business hours, 5 s | High | Telegram + security |
| Loitering | `dwell` person in `restricted` > 300 s | Medium | Alert security |

## 4. Screen rules

| Rule | Condition | Severity | Action |
|---|---|---|---|
| Black screen | `screen` black for 30 s | High | IT alert with screenshot |
| Frozen dashboard | `screen` frozen (perceptual hash unchanged) for 600 s | High | IT alert |
| Error detected | `screen` ocr_match on "Error", "Failed", "Critical" for 5 s | High | IT alert with screenshot |
| Unauthorized app | `screen` unauthorized_app (foreground window not on the allow-list) for 30 s | Medium | Security alert |

## 5. Equipment rules

| Rule | Condition | Severity | Action |
|---|---|---|---|
| Leak detected | `presence` leak ≥ 0.70 for 4 s **[custom model]** | High | Maintenance alert |
| Smoke near machine | `presence` smoke ≥ 0.75 for 3 s **[custom model]** | Critical | Emergency alert; machine stop only if pre-authorised |
| Missing safety guard | `absence` of `guard` class in guard zone for 5 s **[custom model]** | High | Alert supervisor; stop only if pre-authorised |
| Conveyor stopped | `absence` motion in conveyor zone for N s during the production schedule | Medium | Maintenance alert |
| Abnormal heat | Threshold from thermal camera/sensor **[sensor]** | Critical | Emergency action |

## 6. Alert levels
| Level | Meaning | Default response |
|---|---|---|
| Low | Informational | Dashboard only |
| Medium | Operational issue | Dashboard + Telegram |
| High | Security/safety issue | Dashboard + Telegram + email + clip |
| Critical | Fire, intrusion, major equipment risk | All channels + escalation if unacknowledged after 2 min; siren/PLC only per §7 |

## 7. Decision policy
- Alerts are recommendations, not automatic punishments. VisionGuard never identifies individuals (no facial recognition).
- **Physical actions** (`siren`, `plc_stop`, `camera_preset`) default to `requires_approval = true`: an operator approves them from the dashboard or Telegram.
- A customer admin may **pre-authorise** a physical action for a specific critical rule. This needs a written request from the customer, is recorded in the audit log, and is only possible after the rule has run at least 7 days in shadow mode.
- New rules start in `shadow` mode by default.
- Every automated or manual action is logged with event ID, rule ID, actor, timestamp and result.
- Operators can mark false positives. Feedback is stored per model and feeds the next training cycle.
- Alert deliveries retry with backoff (1 min, 5 min, 15 min). After the last failure the event is flagged "undelivered" on the dashboard.
