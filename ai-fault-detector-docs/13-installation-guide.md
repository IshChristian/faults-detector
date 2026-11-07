# Installation Guide

## 1. Requirements
- Ubuntu 22.04 or 24.04 LTS.
- Docker Engine with the Compose plugin, and Git.
- Prototype (core profile, 1–2 cameras): 4 CPU cores, 8 GB RAM. 4 GB works only with one camera and no Label Studio.
- Recommended pilot server: Intel mini PC with iGPU (N100 class or better), 16 GB RAM, 256 GB+ SSD.
- Optional NVIDIA GPU for faster training/inference.

## 2. Install Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Log out and back in.

## 3. Clone and configure

```bash
git clone https://github.com/your-username/visionguard-ai.git
cd visionguard-ai
cp .env.example .env
nano .env
```

Fill in **every** empty value in `.env`. Generate secrets with `openssl rand -base64 32`. Generate the credentials encryption key with:

```bash
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

## 4. Create MQTT users

Mosquitto refuses anonymous clients, so create the password and ACL files before the first start. Both are git-ignored.

```bash
cp mosquitto/config/acl.example mosquitto/config/acl
touch mosquitto/config/passwd
# Use the passwords you put in .env (FRIGATE_MQTT_PASSWORD, MQTT_PASSWORD):
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2.0.20 \
  mosquitto_passwd -b /mosquitto/config/passwd frigate 'FRIGATE_MQTT_PASSWORD_HERE'
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2.0.20 \
  mosquitto_passwd -b /mosquitto/config/passwd visionguard_backend 'MQTT_PASSWORD_HERE'
# Only if you use Node-RED:
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2.0.20 \
  mosquitto_passwd -b /mosquitto/config/passwd nodered 'NODERED_PASSWORD_HERE'
chmod 0700 mosquitto/config/passwd mosquitto/config/acl
```

## 5. Configure cameras

Edit `frigate/config.yml`:
1. Set camera hosts and RTSP credentials in `.env` (`FRIGATE_*` variables).
2. Check the RTSP paths for your camera brand. The examples use Hikvision-style `/Streaming/Channels/101` (main) and `102` (sub).
3. Remove the example cameras you don't have.
4. Redraw zones in the Frigate UI later (Settings → Masks/Zones) and paste the relative coordinates back.

## 6. Start the stack

```bash
docker compose up -d                          # core services
docker compose --profile labeling up -d       # optional: Label Studio
docker compose --profile automation up -d     # optional: Node-RED
docker compose ps
docker compose logs -f backend
```

Services bind to `127.0.0.1` by default:

| Service | URL (on the server) |
|---|---|
| Dashboard | http://localhost:8501 |
| Backend API docs | http://localhost:8100/docs |
| Frigate (authenticated) | https://localhost:8971 (admin password is printed in `docker compose logs frigate` on first start) |
| Label Studio | http://localhost:8080 |
| Node-RED | http://localhost:1880 |

To reach them from another machine during a LAN pilot, either use an SSH tunnel (`ssh -L 8501:localhost:8501 user@server`) or set `BIND_ADDR=0.0.0.0` behind a firewall that only allows the LAN. For internet access, use a reverse proxy with HTTPS (section 8). Never publish PostgreSQL, Valkey or Frigate port 5000.

## 7. Add a camera

1. Open Frigate and confirm the camera shows live video and detections.
2. In the VisionGuard dashboard, add the camera with the same `frigate_name`.
3. Draw zones (use the same names as the Frigate zones).
4. Create a rule from a template. It starts in **shadow** mode.
5. Send a test Telegram alert from Settings → Alert channels.
6. After the shadow period, review its events and switch the rule to **live**.

## 8. Deploy with Coolify (HTTPS, domains, redeploys)

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Coolify's own UI uses host port **8000**. That's why VisionGuard's API is on 8100.

Coolify needs at least 2 CPU cores, 2 GB RAM and 30 GB disk on top of the VisionGuard workload. Create a "Docker Compose" resource pointing at the Git repository, and set domains for `dashboard` (port 8501) and `backend` (port 8000 inside the container). Coolify's proxy then terminates HTTPS. Enter the `.env` values in Coolify's environment settings, not in Git.

## 9. Update

```bash
git pull
docker compose build
docker compose up -d
```

Image tags are pinned in `docker-compose.yml`. To upgrade Frigate or another image, change the tag, read that project's release notes for breaking config changes, and test on a pilot first.

## 10. Backup

The compose project is named `visionguard`, so volume names are predictable.

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > backups/db_$(date +%F).dump
docker run --rm -v visionguard_media_data:/data:ro -v "$PWD/backups":/backup alpine \
  tar czf /backup/media_$(date +%F).tar.gz -C /data .
cp .env backups/env_$(date +%F)   # store encrypted/offline; it contains secrets
```

Schedule this daily with cron and copy `backups/` off the machine. Test a restore monthly:

```bash
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean < backups/db_YYYY-MM-DD.dump
```

Personal data must stay in Rwanda unless NCSA has authorised a transfer (see `11-security-privacy-policy.md`). Choose the off-site backup location accordingly.

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| Mosquitto restarts in a loop | `passwd` or `acl` file missing; repeat section 4 |
| Frigate won't start | Run `docker compose logs frigate`. Frigate refuses invalid config and names the bad key |
| Camera offline | Check RTSP URL, credentials, firewall; test with `ffprobe rtsp://...` |
| High CPU | Use the camera sub-stream for detect, lower detect fps to 5, use the OpenVINO detector, map `/dev/dri` |
| No Telegram alert | Check bot token and chat ID, the `alert_deliveries` table for errors, and outbound internet |
| Dashboard blank | Check `docker compose logs backend` and `BACKEND_URL` |
| Frigate crashes / bus error | Increase `shm_size` |
