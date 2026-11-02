#!/usr/bin/env bash
set -euo pipefail
workspace="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$workspace"
mkdir -p .hdrp-agent/chat
backend_pid=""
cleanup() { if [[ -n "$backend_pid" ]]; then kill -TERM "$backend_pid" 2>/dev/null || true; wait "$backend_pid" 2>/dev/null || true; fi; }
trap cleanup EXIT
healthy() {
  .venv/bin/python - <<'PY'
from pathlib import Path
import httpx,sys
try:
 token=Path('.hdrp-agent/local-token').read_text().strip()
 r=httpx.get('http://127.0.0.1:8765/health',headers={'Authorization':'Bearer '+token},timeout=2)
 sys.exit(0 if r.status_code==200 else 1)
except Exception:sys.exit(1)
PY
}
if ! healthy; then
  .venv/bin/hdrp-agent --env-file .env serve --provider-mode live >.hdrp-agent/chat/backend.log 2>&1 &
  backend_pid=$!
  for _ in {1..30}; do if healthy; then break; fi; if ! kill -0 "$backend_pid" 2>/dev/null; then echo 'The Python service did not start; check .hdrp-agent/chat/backend.log.' >&2; exit 1; fi; sleep 1; done
  healthy || { echo 'Service Python indisponible.' >&2; exit 1; }
fi
(cd apps/unitymapper && go build -o "$workspace/.hdrp-agent/unitymapper" ./cmd/unitymapper)
.hdrp-agent/unitymapper --workspace "$workspace" --open
