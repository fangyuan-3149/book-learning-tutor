#!/usr/bin/env bash
# Regenerate the publish bundle and publish it to ClawHub (with retries).
#
# Usage:
#   NODE_TLS_REJECT_UNAUTHORIZED=0 CLAWHUB_TOKEN=<token> bash publish/publish_retry.sh
#
# Paths are derived from this script's location, so it works wherever the
# repo is cloned. The bundle is regenerated first via build_publish.py.
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -W)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd -W)"
PUBDIR="$REPO (publish)"

# 1) (re)generate the bundle
echo "[build] regenerating bundle from $REPO"
python3 "$SCRIPT_DIR/build_publish.py" || { echo "[build] FAILED"; exit 1; }

TOKEN="${CLAWHUB_TOKEN:-}"
SLUG="book-learning-tutor"
# Bump this before each publish -- ClawHub versions are immutable.
VERSION="0.1.3"
CHANGELOG="Restore full tools/ engine; align with GitHub fangyuan-3149/book-learning-tutor."
REGISTRY="${CLAWHUB_REGISTRY:-https://clawhub.ai}"
SITE="${CLAWHUB_SITE:-https://clawhub.ai}"
MAX=30
SLEEP=5

store_token() {
  [ -z "$TOKEN" ] && { echo "[login] no token provided; relying on CLAWHUB_TOKEN env at publish time"; return 0; }
  for ((i=1;i<=MAX;i++)); do
    echo "[login] attempt $i/$MAX"
    if CLAWHUB_TOKEN="$TOKEN" CLAWDHUB_TOKEN="$TOKEN" \
       npx --yes clawhub@latest login --token "$TOKEN" --label "sandbox-publish" 2>&1; then
      echo "[login] token stored"; return 0
    fi
    read -t "$SLEEP" </dev/null 2>/dev/null || true
  done
  echo "[login] could not store token via network; publish will try CLAWHUB_TOKEN env directly"
}

publish() {
  for ((i=1;i<=MAX;i++)); do
    echo "[publish] attempt $i/$MAX"
    if CLAWHUB_TOKEN="$TOKEN" CLAWDHUB_TOKEN="$TOKEN" \
       CLAWHUB_REGISTRY="$REGISTRY" CLAWHUB_SITE="$SITE" \
       npx --yes clawhub@latest skill publish "$PUBDIR" \
        --slug "$SLUG" --name "Book Learning Tutor" --version "$VERSION" --changelog "$CHANGELOG" \
        --source-repo "https://github.com/fangyuan-3149/book-learning-tutor" \
        --source-commit "$(git -C "$REPO" rev-parse --short HEAD)" \
        --json 2>&1; then
      echo "[publish] SUCCESS"
      return 0
    fi
    echo "[publish] failed (likely TLS drop); retrying in ${SLEEP}s"
    read -t "$SLEEP" </dev/null 2>/dev/null || true
  done
  echo "[publish] FAILED after $MAX attempts"
  return 1
}

store_token
publish
