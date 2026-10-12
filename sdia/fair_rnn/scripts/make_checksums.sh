#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT=frozen/MANIFEST_SHA256.txt
{
  echo "# fair_RNN overnight pack checksums $(date '+%F %T %z')"
  echo "# S3=CLOSED E2b=untouched"
  find . -type f ! -path './logs/*' ! -path './tune/*' ! -path './genes/*' ! -path './__pycache__/*' ! -path './code/__pycache__/*' \
    ! -name 'MANIFEST_SHA256.txt' | sort | while read -r f; do
    sha256sum "$f"
  done
} > "$OUT"
echo "WROTE $OUT"
wc -l "$OUT"
