#!/usr/bin/env bash
# ============================================================
# migrate.sh — Render → Google Cloud Run migration
# Service: property-video-generator (FastAPI + FFmpeg)
# Repo:    mdforcum/property-video-generator
#
# Run from the REPO ROOT:  bash migrate.sh
# Safe to re-run — every step is idempotent.
#
# Prereqs (one-time, manual):
#   1. Google account + billing enabled (console.cloud.google.com)
#   2. gcloud CLI installed:
#        Windows: https://cloud.google.com/sdk/docs/install
#        (run in Git Bash or WSL; or use the PowerShell notes in README)
#   3. gcloud auth login   (already logged in)
# ============================================================
set -euo pipefail

# ---------- Configuration (edit if desired) ----------
PROJECT_ID="${PROJECT_ID:-shelby-video}"
REGION="${REGION:-us-central1}"          # Iowa — Tier 1 pricing, closest to IL
REPO_NAME="shelby-images"
SERVICE_NAME="property-video-generator"
MEMORY="2Gi"                              # FFmpeg needs headroom
CPU="1"
TIMEOUT="900"                             # MAX_JOB_SECONDS=420 → 900s is ample
MAX_INSTANCES="2"                         # bill-shock guardrail
# -----------------------------------------------------

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die()  { printf '\n❌ %s\n' "$*" >&2; exit 1; }

[ -f "apps/backend/Dockerfile" ] || die "Run this from the repo root (apps/backend/Dockerfile not found)."
command -v gcloud >/dev/null || die "gcloud CLI not found. Install it first."

bold "Step 0/7 — Verify auth"
gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@" \
  || die "Not logged in. Run: gcloud auth login"

bold "Step 1/7 — Project: $PROJECT_ID"
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name="Shelby Video"
  echo "⚠️  Now link billing: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
  read -rp "Press Enter once billing is linked..."
fi
gcloud config set project "$PROJECT_ID" --quiet

bold "Step 2/7 — Enable APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com --quiet

bold "Step 3/7 — Artifact Registry: $REPO_NAME"
gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO_NAME" \
       --repository-format=docker --location="$REGION" \
       --description="Shelby container images"

bold "Step 4/7 — Secrets (Supabase, GreatSchools, Mapbox)"
# Pulls values from apps/backend/.env if present; otherwise prompts.
ENV_FILE="apps/backend/.env"
get_val() {  # get_val KEY
  [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true
}
ensure_secret() {  # ensure_secret NAME KEY
  local name="$1" key="$2" val
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    echo "  ✓ secret $name exists (skipping)"
    return
  fi
  val="$(get_val "$key")"
  if [ -z "$val" ]; then
    read -rsp "  Enter value for $key: " val; echo
  fi
  [ -z "$val" ] && { echo "  ⤼ skipped $name (empty)"; return; }
  printf '%s' "$val" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic
  echo "  ✓ created secret $name"
}
ensure_secret supabase-url               SUPABASE_URL
ensure_secret supabase-service-role-key  SUPABASE_SERVICE_ROLE_KEY
ensure_secret greatschools-api-key       GREATSCHOOLS_API_KEY
ensure_secret mapbox-token               MAPBOX_TOKEN

# Grant Cloud Run's service account access to secrets
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for s in supabase-url supabase-service-role-key greatschools-api-key mapbox-token; do
  gcloud secrets describe "$s" >/dev/null 2>&1 && \
    gcloud secrets add-iam-policy-binding "$s" \
      --member="serviceAccount:$RUN_SA" --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
done

bold "Step 5/7 — Build & push image (Cloud Build)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:latest"
gcloud builds submit apps/backend --tag "$IMAGE"

bold "Step 6/7 — Deploy to Cloud Run"
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --memory "$MEMORY" \
  --cpu "$CPU" \
  --timeout "$TIMEOUT" \
  --concurrency 1 \
  --no-cpu-throttling \
  --min-instances 0 \
  --max-instances "$MAX_INSTANCES" \
  --set-secrets "SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,GREATSCHOOLS_API_KEY=greatschools-api-key:latest,MAPBOX_TOKEN=mapbox-token:latest" \
  --set-env-vars "ENABLE_BACKGROUND_AUDIO=false,MAX_SOURCE_IMAGES=24,MAX_JOB_SECONDS=420,FFMPEG_TIMEOUT_SECONDS=360,MAX_CONCURRENT_GENERATIONS=1,FRONTEND_ORIGINS=https://shelby-video-frontend.onrender.com"

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)')"

bold "Step 7/7 — Done. Verify:"
echo "  Service URL:  $SERVICE_URL"
echo "  Health check: curl $SERVICE_URL/health"
echo
echo "NEXT (manual):"
echo "  1. Set budget alerts (\$5 and \$20):"
echo "     https://console.cloud.google.com/billing/budgets?project=$PROJECT_ID"
echo "  2. Update the frontend backend URL:"
echo "     apps/frontend/index.html → replace"
echo "       https://property-video-generator.onrender.com"
echo "     with"
echo "       $SERVICE_URL"
echo "  3. Update FRONTEND_ORIGINS if/when the frontend moves to Vercel."
echo "  4. Run one real video job end-to-end."
echo "  5. SUSPEND (don't delete) the Render service for a 1-week fallback,"
echo "     then delete it and downgrade the Render team plan to Hobby."
