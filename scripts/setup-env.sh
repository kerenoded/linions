#!/usr/bin/env bash
#
# Syncs local development configuration from the deployed Linions AWS stack.
#
# Responsibilities:
# - read CloudFormation outputs from `LinionsStack`
# - write `proxy/.env` with the latest Function URLs, CloudFront domain, bucket name, and region
# - optionally sync `knowledge-base/` into the deployed KB bucket when LINIONS_SYNC_KB=1
# - trigger and wait for a Bedrock Knowledge Base ingestion job unless explicitly skipped
#
# Re-run this after the first deploy and after any later deploy that changes stack outputs.

set -euo pipefail

STACK_NAME="LinionsStack"
AWS_PROFILE_VALUE="${AWS_PROFILE:-default}"
OUTPUT_FILE="proxy/.env"

if ! command -v aws >/dev/null 2>&1; then
  echo "Error: aws CLI is required but was not found in PATH." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required but was not found in PATH." >&2
  exit 1
fi

STACK_JSON="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --profile "$AWS_PROFILE_VALUE")"

extract_output() {
  local key="$1"
  local value
  value="$(echo "$STACK_JSON" | jq -r --arg key "$key" '.Stacks[0].Outputs[] | select(.OutputKey == $key) | .OutputValue' | head -n 1)"
  if [[ -z "$value" || "$value" == "null" ]]; then
    echo "Error: required stack output '$key' was not found in stack '$STACK_NAME'." >&2
    exit 1
  fi
  printf '%s' "$value"
}

GENERATE_URL="$(extract_output "GenerateFunctionUrl")"
STATUS_URL="$(extract_output "StatusFunctionUrl")"
CLOUDFRONT_DOMAIN="$(extract_output "CloudFrontDomain")"
EPISODES_BUCKET="$(extract_output "EpisodesBucketName")"
AWS_REGION_VALUE="$(aws configure get region --profile "$AWS_PROFILE_VALUE" 2>/dev/null || true)"
if [[ -z "$AWS_REGION_VALUE" ]]; then
  AWS_REGION_VALUE="${AWS_REGION:-}"
fi
if [[ -z "$AWS_REGION_VALUE" ]]; then
  echo "Error: could not determine AWS region. Set AWS_REGION or configure a region for profile '$AWS_PROFILE_VALUE'." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_FILE")"
TMP_FILE="$(mktemp "${OUTPUT_FILE}.tmp.XXXXXX")"

cat >"$TMP_FILE" <<EOF_ENV
AWS_PROFILE=${AWS_PROFILE_VALUE}
AWS_REGION=${AWS_REGION_VALUE}
LINIONS_GENERATE_URL=${GENERATE_URL}
LINIONS_STATUS_URL=${STATUS_URL}
CLOUDFRONT_DOMAIN=${CLOUDFRONT_DOMAIN}
EPISODES_BUCKET=${EPISODES_BUCKET}
EOF_ENV

mv "$TMP_FILE" "$OUTPUT_FILE"

echo "Wrote ${OUTPUT_FILE} from CloudFormation stack ${STACK_NAME}."

if [[ "${LINIONS_SYNC_KB:-0}" == "1" ]]; then
  KNOWLEDGE_BASE_BUCKET="$(extract_output "KnowledgeBaseBucketName")"
  echo "Syncing knowledge-base/ to s3://${KNOWLEDGE_BASE_BUCKET} because LINIONS_SYNC_KB=1..."
  aws s3 sync knowledge-base/ "s3://${KNOWLEDGE_BASE_BUCKET}" \
    --delete \
    --profile "$AWS_PROFILE_VALUE" \
    --region "$AWS_REGION_VALUE"
fi

if [[ "${LINIONS_SKIP_KB_INGEST:-0}" == "1" ]]; then
  echo "Skipping KB ingestion trigger because LINIONS_SKIP_KB_INGEST=1."
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required to trigger Bedrock KB ingestion." >&2
  exit 1
fi

echo "Triggering Bedrock Knowledge Base ingestion..."
python3 scripts/start-kb-ingestion.py \
  --stack-name "$STACK_NAME" \
  --profile "$AWS_PROFILE_VALUE" \
  --region "$AWS_REGION_VALUE" \
  --wait
