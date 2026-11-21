# Deploying Nazar on AWS (us-west-2)

One CPU EC2 instance runs MediaMTX + API (with the edge manager) + worker + Caddy (HTTPS). Postgres is RDS with
pgvector, media is S3 with a 7-day lifecycle, the web app is a static export on Amplify Hosting.

```
phone (Larix SRT/RTMP) ──► EC2 ── mediamtx ─rtsp─► edge(s) ─┐
                             │  api (FastAPI + edge manager) ├──► RDS Postgres + pgvector
browser (Amplify PWA) ──https─► caddy ─► api                 │
                             │  worker (eventize/rules/enrich)┘──► S3 (crops, clips, TTS, snapshots)
```

**Guardrails (from the organizers):** no GPU instances (g\*, p\*, inf\*, trn\*), no Bedrock, exactly ONE EC2
instance, no fleets. Workshop CLI keys are temporary — the server never uses them (it uses an instance role).
Nothing here is created automatically: every step is a console click you do yourself.

---

## 1. S3 bucket (media)
1. S3 → **Create bucket** → name `nazar-media-<random>` (e.g. `nazar-media-7f3k2`), region **us-west-2**.
2. **Block all public access: ON** (default). Create.
3. Open the bucket → **Management** → **Create lifecycle rule** → name `expire-7d` → apply to all objects →
   **Expire current versions of objects** after **7** days → Create.

## 2. IAM role for the instance
1. IAM → Policies → **Create policy** → JSON:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        "Resource": "arn:aws:s3:::nazar-media-<random>/*"},
       {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::nazar-media-<random>"}
     ]
   }
   ```
   Name it `nazar-s3-media`.
2. IAM → Roles → **Create role** → trusted entity **AWS service → EC2** → attach `nazar-s3-media` → name
   `nazar-ec2-role`.

## 3. Security groups
1. EC2 → Security Groups → **Create** `nazar-ec2-sg` (default VPC), inbound:
   | Type | Port | Source |
   |---|---|---|
   | SSH | 22 | My IP |
   | HTTP | 80 | 0.0.0.0/0 |
   | HTTPS | 443 | 0.0.0.0/0 |
   | Custom UDP | 8890 | 0.0.0.0/0 (SRT from phones; a publish path is required) |
   | Custom TCP | 1935 | 0.0.0.0/0 (RTMP from phones) |
2. **Create** `nazar-db-sg`, inbound: PostgreSQL 5432 from source **`nazar-ec2-sg`** only.

## 4. RDS PostgreSQL
1. RDS → **Create database** → Standard create → **PostgreSQL 16** → template **Free tier / Dev-Test**.
2. DB instance identifier `nazar-db`, master user `nazar`, set a password.
3. Instance **db.t4g.micro**, storage **20 GB gp3**, no storage autoscaling needed.
4. Connectivity: default VPC, **Public access: No**, security group **`nazar-db-sg`**.
5. Additional configuration → Initial database name **`nazar`**. Create (takes ~5–10 min).
6. Note the endpoint, e.g. `nazar-db.xxxxxxxx.us-west-2.rds.amazonaws.com`. The `vector` and `pg_trgm` extensions
   are created by Nazar's first migration (RDS supports pgvector).

## 5. EC2 instance (exactly one, CPU only)
1. EC2 → **Launch instance** → name `nazar` → **Ubuntu Server 24.04 LTS** (x86_64).
2. Instance type **c7i.xlarge** (4 vCPU, 8 GB). *Not* g\*/p\*/inf\*/trn\*.
3. Key pair: create/download one (e.g. `nazar-key.pem`).
4. Network: security group **`nazar-ec2-sg`**. Storage **60 GB gp3**.
5. Advanced details → IAM instance profile **`nazar-ec2-role`**. Launch.
6. EC2 → **Elastic IPs** → Allocate → Associate with the `nazar` instance. Your domain is the IP with dashes:
   `34.210.12.7` → **`34-210-12-7.sslip.io`** (free HTTPS via Caddy, no domain purchase).

## 6. Install and start on the instance
From PowerShell on your laptop:
```powershell
ssh -i .\nazar-key.pem ubuntu@<elastic-ip>
```
On the instance:
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu && newgrp docker
git clone https://github.com/Shivansh0911/Nazar.git && cd Nazar
cp .env.example .env && nano .env
```
Production `.env` values (everything else can stay default):
```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://nazar:<password>@<rds-endpoint>:5432/nazar
STORAGE_MODE=s3
S3_BUCKET=nazar-media-<random>
AWS_REGION=us-west-2
DOMAIN=<elastic-ip-with-dashes>.sslip.io
API_BASE_URL=https://<elastic-ip-with-dashes>.sslip.io
PUBLIC_HOST=<elastic-ip>
WEB_ORIGINS=https://main.<amplify-app-id>.amplifyapp.com
DEMO_PASSCODE=<choose one>
```
Leave `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` **empty** — boto3 uses the instance role.
Then:
```bash
docker compose -f infra/docker-compose.prod.yml up -d --build
docker compose -f infra/docker-compose.prod.yml exec api python -m nazar.core.migrate
docker compose -f infra/docker-compose.prod.yml exec api python /app/scripts/download_models.py --export-cpu
docker compose -f infra/docker-compose.prod.yml restart api worker
curl -s https://<elastic-ip-with-dashes>.sslip.io/api/health
```
(No RDS? `docker compose -f infra/docker-compose.prod.yml --profile db up -d --build` with
`DATABASE_URL=postgresql://nazar:nazar@postgres:5432/nazar`.)

Optional demo data on the server: copy `samples/*.mp4` with `scp`, then
`docker compose -f infra/docker-compose.prod.yml exec api python /app/scripts/demo_setup.py` (the samples folder is
baked into the image without videos — mount or copy them into `/app/samples`).

## 7. Web on Amplify Hosting
On your laptop (PowerShell):
```powershell
cd web
$env:NEXT_PUBLIC_API_BASE_URL="https://<elastic-ip-with-dashes>.sslip.io"
npm run build
Compress-Archive -Path out\* -DestinationPath nazar-web.zip -Force
```
Amplify → **Create new app** → **Deploy without Git** → upload `nazar-web.zip` → Save and deploy. Copy the app URL
into `WEB_ORIGINS` in the server `.env` and `docker compose ... restart api`.
(Alternative: connect the GitHub repo, app root `web`, build `npm ci && npm run build`, artifacts `out`, and an
environment variable `NEXT_PUBLIC_API_BASE_URL`.)

## 8. Phone camera (Larix Broadcaster)
1. In the web app: Cameras → Add camera → **Phone** → name `hall-1` → it shows
   `srt://<elastic-ip>:8890?streamid=publish:hall-1` (and `rtmp://<elastic-ip>/hall-1`) with a QR code.
2. Larix → Settings → Connections → New → paste/scan the URL. Video: 1280×720, 15 fps, 2–3 Mbps, H.264.
3. Press **Create & start** in the app (source `rtsp://mediamtx:8554/hall-1`), then start streaming in Larix.
   Streaming to the EC2 public IP avoids venue Wi-Fi client isolation.

## 9. Guardrails checklist
- [ ] Exactly one EC2 instance, type c7i.xlarge (CPU). No GPU types, no Bedrock, no fleets/ASGs.
- [ ] Billing → Budgets → a budget alert (e.g. $25) on the account.
- [ ] `RECORD_RAW_BOOL` unset (raw recording off) unless you need overnight recordings.
- [ ] S3 lifecycle `expire-7d` in place; bucket not public.
- [ ] After the event: terminate the instance, release the Elastic IP, delete RDS (skip final snapshot if not
      needed), empty + delete the bucket, delete the Amplify app.

## Troubleshooting
- `ExpiredToken` / `InvalidClientTokenId` from the AWS CLI on your laptop → refresh the Workshop credentials.
- Caddy can't get a certificate → ports 80/443 must be open and `DOMAIN` must match the Elastic IP.
- Edge on CPU too slow → `python /app/scripts/download_models.py --export-cpu` (OpenVINO) and keep `MAX_EDGES=3`.
