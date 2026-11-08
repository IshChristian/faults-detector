# Security and Privacy Policy

## 1. Data collected
- Camera video frames and short clips.
- Detection metadata: time, camera, object class, confidence, bounding box.
- Screen screenshots and OCR text when screen monitoring is enabled.
- User account information.
- Alert delivery logs.

## 2. Data minimization
- Record event clips, not continuous 24/7 cloud video, unless the customer explicitly requests it.
- Use the lowest resolution needed for reliable detection.
- Store only fault-related snapshots and clips by default.
- Do not collect biometric identifiers in version 1.

## 3. Access control
- Use role-based access:
  - Super admin: full platform access.
  - Customer admin: own sites and users.
  - Operator: live view and event review.
  - Viewer: dashboard and reports only.
- Enforce JWT authentication.
- Use HTTPS for all external dashboard access.
- Keep MQTT, PostgreSQL, Valkey, object storage and Frigate on the internal Docker network; bind host ports to 127.0.0.1 and expose only the dashboard and API through an HTTPS reverse proxy.
- Rate-limit login; lock accounts after repeated failures; hash passwords with argon2id.
- Rotate refresh tokens on every use; revoke on logout and password change.

## 4. Retention
Default retention:
- Event snapshots: 14 days.
- Event clips: 14 days.
- Detection metadata: 12 months.
- Training datasets: until model deletion or customer request.
- User audit logs: 12 months.

Customers may request shorter or longer retention.

## 5. Privacy safeguards
- Inform staff and visitors that CCTV/AI monitoring is in use where legally required.
- Avoid cameras in private areas such as toilets and changing rooms.
- Provide optional face blurring for exported clips.
- Restrict footage export to authorized users.
- Log every export and manual action.

## 6. Security controls
- Change all default passwords.
- Use strong, unique credentials for PostgreSQL, MQTT (one user per client, with ACLs), object storage and Frigate.
- Enable firewall rules; expose only dashboard and API ports.
- Keep Docker images updated.
- Back up PostgreSQL and media daily; test a restore monthly.
- Store secrets in `.env`, never in Git.
- Use separate credentials per customer camera; store them encrypted at rest and never return them from the API.
- Pin container image versions; review release notes before upgrading.
- Sign outgoing webhooks (HMAC-SHA256) so receivers can verify them.

## 7. Legal compliance — Rwanda (Law No. 058/2021 on the protection of personal data and privacy)
CCTV footage of identifiable people is personal data. The supervisory authority is the **National Cyber Security Authority (NCSA)**.

| Obligation | How VisionGuard meets it |
|---|---|
| Register as a data controller/processor with NCSA | VisionGuard (as processor) and each customer (as controller) register before go-live. Track the certificate number in the customer record. |
| Store personal data in Rwanda unless NCSA authorises transfer | Default deployment is on the customer's premises or a Rwanda-hosted server. Off-site backups and any cloud AI service must stay in Rwanda or have NCSA authorisation. |
| Notify NCSA of a personal-data breach within 48 hours | Incident response step 4 below. |
| Inform data subjects | Signage at monitored areas, stating the controller, purpose and contact. Template in the customer onboarding pack. |
| Purpose limitation and minimisation | Event clips only by default, configurable retention, no biometrics. |
| Data-subject rights (access, deletion) | Customer admin can search and export or delete events by camera and time window; every request is logged. |

Customer contracts include a data processing agreement: who is controller and processor, the retention period, where data is hosted, sub-processors, and breach-notice duties. This section is guidance, not legal advice. Have a Rwandan lawyer confirm it before the first paid deployment.

## 8. Incident response
1. Identify affected system and customer.
2. Stop further exposure by disabling affected camera/access.
3. Preserve logs.
4. Notify the customer admin immediately, and NCSA within 48 hours if personal data was exposed.
5. Patch vulnerability.
6. Review false alerts or data exposure.
7. Document root cause and prevention.
