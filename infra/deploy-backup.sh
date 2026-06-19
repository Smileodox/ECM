#!/usr/bin/env bash
#
# deploy-backup.sh — stand up a full hot-replica of the campusLMU chatbot in a
# second Azure subscription (backup / disaster-recovery).
#
# Provisions all infra (self-contained Bicep, keys derived via listKeys),
# pushes backend + frontend app code, and prints the data-ingestion follow-up.
#
# Prereqs:
#   - az CLI logged in (`az login`), with rights in the target subscription
#     (Contributor; PIM elevation if applicable — see deploy-access notes).
#   - Model quota for gpt-5.4 / gpt-5.4-nano / text-embedding-3-small approved
#     in the target subscription BEFORE running (else model deployments fail).
#   - Run from the repo root: `infra/deploy-backup.sh`
#
# Config via env vars (with defaults):
#   BACKUP_SUB_ID   target subscription id           (required)
#   RG              resource group name              (rg-chatbot-backup)
#   LOCATION        Azure region                     (westeurope)
#   PROJECT_NAME    must match main.backup.bicepparam (chatbot)
#   ENVIRONMENT     must match main.backup.bicepparam (backup)
#
set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────
BACKUP_SUB_ID="${BACKUP_SUB_ID:?set BACKUP_SUB_ID to the target subscription id}"
RG="${RG:-rg-chatbot-backup}"
LOCATION="${LOCATION:-westeurope}"
PROJECT_NAME="${PROJECT_NAME:-chatbot}"
ENVIRONMENT="${ENVIRONMENT:-backup}"

# Resource names — must mirror the derivation in main.bicep
BACKEND_APP="app-${PROJECT_NAME}-backend-${ENVIRONMENT}"
FRONTEND_APP="app-${PROJECT_NAME}-frontend-${ENVIRONMENT}"
OPENAI_NAME="oai-${PROJECT_NAME}-${ENVIRONMENT}"
SEARCH_NAME="search-${PROJECT_NAME}-${ENVIRONMENT}"

# Resolve paths relative to this script so it works from any CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "▶ Target subscription: ${BACKUP_SUB_ID}"
az account set --subscription "${BACKUP_SUB_ID}"

# ─── 1. Resource group ──────────────────────────────────────────────────────
# Mandatory SKF governance tags — also applied to every resource inside the
# template (see `tags` param in main.bicep). Override TAGS to change them.
TAGS="${TAGS:-apmid=apm0006827 billingidentifier=cl_op_azure fso=paul.keck@skf.com itso=paul.keck@skf.com}"
echo "▶ Creating resource group ${RG} (${LOCATION})"
# shellcheck disable=SC2086
az group create -n "${RG}" -l "${LOCATION}" --tags ${TAGS} -o none

# ─── 2. Infra (Bicep) ────────────────────────────────────────────────────────
echo "▶ Deploying infrastructure (this also creates the model deployments)…"
DEPLOY_OUT="$(az deployment group create \
  -g "${RG}" \
  -f "${SCRIPT_DIR}/main.bicep" \
  -p "${SCRIPT_DIR}/main.backup.bicepparam" \
  --query properties.outputs -o json)"

BACKEND_URL="$(echo "${DEPLOY_OUT}"  | python3 -c 'import sys,json;print(json.load(sys.stdin)["backendUrl"]["value"])')"
FRONTEND_URL="$(echo "${DEPLOY_OUT}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["frontendUrl"]["value"])')"
echo "  backend : ${BACKEND_URL}"
echo "  frontend: ${FRONTEND_URL}"

# ─── 3. Backend app code (source zip, Oryx builds it) ────────────────────────
echo "▶ Packaging + deploying backend…"
BACKEND_ZIP="${WORK}/backend.zip"
# The regulation manifest drives version filtering + program detection at runtime.
# It lives in documents/ (with the PDFs, NOT in the backend zip), so refresh the
# shipped copy and add it explicitly — data/* is otherwise excluded (web_manifest is 1.6M).
cp "${REPO_ROOT}/documents/manifest.json" "${REPO_ROOT}/backend/data/manifest.json"
( cd "${REPO_ROOT}/backend" && zip -q -r "${BACKEND_ZIP}" . \
    -x '*.pyc' -x '__pycache__/*' -x '*/__pycache__/*' \
    -x '.venv/*' -x 'tests/*' -x 'data/*' -x '.pytest_cache/*' -x '.env' \
  && zip -q "${BACKEND_ZIP}" data/manifest.json )
az webapp deploy -g "${RG}" -n "${BACKEND_APP}" --src-path "${BACKEND_ZIP}" \
  --type zip --clean false -o none
echo "  backend deployed."

# ─── 4. Frontend app code (PREBUILT standalone) ──────────────────────────────
# NEXT_PUBLIC_API_URL is inlined at build time → must be baked in NOW, pointing
# at THIS deployment's backend, not the primary one.
echo "▶ Building + deploying frontend (prebuilt standalone)…"
(
  cd "${REPO_ROOT}/frontend"
  rm -rf .next
  NEXT_PUBLIC_API_URL="${BACKEND_URL}" npm run build
  # outputFileTracingRoot is ../../ → standalone lands here:
  STANDALONE=".next/standalone/chatbot_poc/frontend"
  cp -r .next/static "${STANDALONE}/.next/static"
  cp -r public       "${STANDALONE}/public"
  ( cd "${STANDALONE}" && zip -q -r "${WORK}/frontend.zip" . )
)
az webapp deployment source config-zip -g "${RG}" -n "${FRONTEND_APP}" \
  --src "${WORK}/frontend.zip" -o none
echo "  frontend deployed."

# ─── 5. Next steps (data ingestion — required for a working replica) ─────────
cat <<EOF

✅ Infra + app code deployed.
   Frontend: ${FRONTEND_URL}
   Backend : ${BACKEND_URL}

⚠️  The search indices are EMPTY. The bot won't answer until you ingest data.
   Fetch the backup endpoints + keys, point a local .env at them, then ingest:

   SEARCH_ENDPOINT=https://${SEARCH_NAME}.search.windows.net
   SEARCH_KEY=\$(az search admin-key show -n ${SEARCH_NAME} -g ${RG} --query primaryKey -o tsv)
   OPENAI_ENDPOINT=\$(az cognitiveservices account show -n ${OPENAI_NAME} -g ${RG} --query properties.endpoint -o tsv)
   OPENAI_KEY=\$(az cognitiveservices account keys list -n ${OPENAI_NAME} -g ${RG} --query key1 -o tsv)

   # Regulations (PDFs already in documents/):
   curl -X POST ${BACKEND_URL}/api/ingest
   # Web content (web_manifest.json already in backend/data/):
   cd backend && uv run python ingest_web.py

   Then smoke-test: ask a question in the frontend → expect [Quelle N] citations.
EOF
