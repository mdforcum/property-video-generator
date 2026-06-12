# Render → Cloud Run Migration

**Goal:** ~$69/mo projected Render spend → ~$0–10/mo on Google Cloud Run.

## What's in this package

| File | Purpose |
|---|---|
| `migrate.sh` | One-command guided migration. Idempotent — safe to re-run. |
| `Makefile` | Day-2 ops: `make deploy`, `make logs`, `make health` |

## How to run (Windows)

The script is bash. Two options:

**Option A — Git Bash** (you already have it with Git for Windows):
```
cd path\to\property-video-generator
bash migrate.sh
```

**Option B — Claude Code** (recommended): drop both files into the repo
root, then tell Claude Code: *"Run migrate.sh and walk me through any
prompts or errors."* It will execute, diagnose failures, and fix them live.

## One-time prerequisites (must be you, ~10 min)

1. Google account → console.cloud.google.com → enable billing (card required;
   expected charges $0–10/mo)
2. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
3. `gcloud auth login`

## What the script does

1. Creates project `shelby-video`, enables APIs
2. Creates Artifact Registry repo
3. Stores your 4 secrets in Secret Manager (reads `apps/backend/.env`
   if present, prompts otherwise)
4. Builds the Docker image via Cloud Build (FFmpeg + Python 3.11)
5. Deploys to Cloud Run: 2Gi RAM, 900s timeout, concurrency 1,
   no CPU throttling, scale-to-zero, **max 2 instances** (bill guardrail)
6. Prints the new service URL + next steps

## After migration

1. **Budget alerts** — set $5 and $20 alerts (script prints the link)
2. **Frontend** — swap `https://property-video-generator.onrender.com`
   for the new Cloud Run URL in `apps/frontend/index.html`, redeploy
   the frontend (it already has a `vercel.json` — Vercel free tier works)
3. **Test** one real video generation end-to-end
4. **Suspend** Render service (keep 1 week as fallback), then delete
5. **Downgrade** Render team plan Professional → Hobby (saves $19/mo)
6. **auto-reel-backend** — not in this repo. Decide: legacy (delete on
   Render = instant $13.48/mo savings) or active (needs its own
   migration pass — same script pattern, different repo)

## Known tradeoff: cold starts

First request after ~15 min idle takes 5–30s while the container spins
up. For a few-times-a-week internal tool this is fine. If it ever
becomes annoying: `gcloud run services update property-video-generator
--min-instances 1` (costs ~$10–15/mo — defeats most savings).

## Future: the automation pipeline cron

The social-media automation pipeline (scraper → event detector →
/publish) used Render's free cron. On GCP the equivalent is **Cloud
Scheduler** hitting a Cloud Run endpoint every 30 min — free tier covers
it (3 scheduler jobs free). When the pipeline files are merged and the
data-feed question (iHOUSEweb vs CIBOR) is resolved:

```
gcloud scheduler jobs create http scrape-and-dispatch \
  --schedule="*/30 * * * *" \
  --uri="<SERVICE_URL>/cron/scrape" \
  --http-method=POST \
  --location=us-central1 \
  --oidc-service-account-email=<RUN_SA>
```

(The pipeline's cron entry point will need a thin HTTP wrapper route —
a 10-line addition when we get there.)

## Cost expectation

| Item | Render (now) | Cloud Run (after) |
|---|---|---|
| property-video-generator | $13.48/mo | ~$0–5/mo (free tier likely) |
| auto-reel-backend | $13.48/mo | $0 if legacy; ~$0–5 if migrated |
| Team plan | $19/mo | $0 (Hobby) |
| Frontend | $0 | $0 (Vercel) |
| **Total** | **~$46–69/mo** | **~$0–10/mo** |
