#!/usr/bin/env bash
# Usage:
#   REMOTE_CACHE=grpcs://cache.example.com REMOTE_INSTANCE_NAME=... REMOTE_TOKEN=... ./repro.sh
# REMOTE_TOKEN is optional; when set it is sent as "Authorization: Bearer <token>".
set -euo pipefail
cd "$(dirname "$0")"
: "${REMOTE_CACHE:?set REMOTE_CACHE, e.g. grpcs://cache.example.com}"
: "${REMOTE_INSTANCE_NAME:?set REMOTE_INSTANCE_NAME}"

flags=(
  --remote_cache="$REMOTE_CACHE"
  --remote_instance_name="$REMOTE_INSTANCE_NAME"
  --remote_upload_local_results=true
  # Fresh action keys on every run, so step 1 always executes and uploads.
  --action_env=REPRO_SALT="$(date +%s)-$$"
)
if [[ -n "${REMOTE_TOKEN:-}" ]]; then
  flags+=(--remote_cache_header="Authorization=Bearer $REMOTE_TOKEN")
fi
mkdir -p logs

summary() { grep -Eo '[0-9]+ process(es)?: .*' || true; }

echo "== 1. Build both targets: each action runs locally and uploads its result"
bazel build "${flags[@]}" --remote_grpc_log="$PWD/logs/1-upload.grpclog" //... 2>&1 | summary

echo "== 2. bazel clean --expunge (drop every local output and local cache)"
bazel clean --expunge 2>/dev/null

echo "== 3. Build each target again: both should be remote cache hits"
missed=0
for target in dir_with_empty_file dir_with_one_byte_file; do
  line=$(bazel build "${flags[@]}" --remote_grpc_log="$PWD/logs/3-$target.grpclog" "//:$target" 2>&1 | summary)
  if [[ "$line" == *"remote cache hit"* ]]; then
    verdict="HIT"
  else
    verdict="MISS (executed again)"
    missed=1
  fi
  printf '%-26s %-22s %s\n' "//:$target" "$verdict" "$line"
done

echo "Bazel's gRPC logs of every cache call (--remote_grpc_log): logs/"
exit "$missed"
