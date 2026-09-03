#!/usr/bin/env bash
# One-time GCP setup so the deploy-api GitHub Action can push to Cloud Run
# with Workload Identity Federation (no service-account key file).
#
# Prereqs:  gcloud CLI, logged in (`gcloud auth login`), a GCP project with
#           billing enabled (the Cloud Run free tier covers hobby traffic).
#
# Usage:    GCP_PROJECT=my-project bash server/gcp-setup.sh
#           (GCP_REGION defaults to asia-south1, GITHUB_REPO to manasij123/desktop-scanner)
set -euo pipefail

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${GCP_REGION:-asia-south1}"
REPO_SLUG="${GITHUB_REPO:-manasij123/desktop-scanner}"
SA_NAME="gh-deploy-cloudrun"
POOL="github-pool"
PROVIDER="github-provider"

[ -n "$PROJECT" ] || { echo "Set GCP_PROJECT (or: gcloud config set project <id>)"; exit 1; }
PNUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA_EMAIL="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
echo ">> project $PROJECT ($PNUM) | region $REGION | repo $REPO_SLUG"

echo ">> enabling APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iamcredentials.googleapis.com \
  iam.googleapis.com --project "$PROJECT"

echo ">> deploy service account..."
gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
  --display-name "GitHub Actions - Cloud Run deploy" 2>/dev/null || true
for role in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.admin roles/iam.serviceAccountUser \
            roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$SA_EMAIL" --role "$role" --condition=None -q >/dev/null
done
# let the deploy SA act as the runtime / Cloud Build SAs
for svc in "$PNUM-compute@developer.gserviceaccount.com" \
           "$PNUM@cloudbuild.gserviceaccount.com"; do
  gcloud iam service-accounts add-iam-policy-binding "$svc" --project "$PROJECT" \
    --member "serviceAccount:$SA_EMAIL" --role roles/iam.serviceAccountUser \
    --condition=None -q >/dev/null 2>&1 || true
done

echo ">> workload identity federation..."
gcloud iam workload-identity-pools create "$POOL" --project "$PROJECT" \
  --location global --display-name "GitHub" 2>/dev/null || true
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --project "$PROJECT" --location global --workload-identity-pool "$POOL" \
  --display-name "GitHub OIDC" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition "assertion.repository=='$REPO_SLUG'" \
  --issuer-uri "https://token.actions.githubusercontent.com" 2>/dev/null || true

POOL_ID="$(gcloud iam workload-identity-pools describe "$POOL" --project "$PROJECT" \
  --location global --format='value(name)')"
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" --project "$PROJECT" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/$POOL_ID/attribute.repository/$REPO_SLUG" -q >/dev/null
PROVIDER_ID="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --project "$PROJECT" --location global --workload-identity-pool "$POOL" \
  --format='value(name)')"

cat <<EOF

============================================================================
Done. Add these as repo VARIABLES:
  GitHub repo -> Settings -> Secrets and variables -> Actions -> Variables tab

  GCP_PROJECT        $PROJECT
  GCP_REGION         $REGION
  GCP_WIF_PROVIDER   $PROVIDER_ID
  GCP_DEPLOY_SA      $SA_EMAIL

Then push a change under server/ (or run the deploy-api workflow manually).
============================================================================
EOF
