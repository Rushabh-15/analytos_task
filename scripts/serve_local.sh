#!/usr/bin/env bash
# Apply the declarative cluster and serve Omnigraph locally with bearer auth.
# Reads tokens from .env. Re-run after editing schemas/queries/policies —
# applied changes are served after (re)start.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && set -a && . ./.env && set +a
: "${TOK_ADMIN:?run scripts/bootstrap.sh and fill .env first}"
: "${TOK_REVIEWER:?}"; : "${TOK_INGEST:?}"; : "${TOK_CONTENT:?}"; : "${TOK_GTM:?}"

BIND="${OMNIGRAPH_BIND:-127.0.0.1:8080}"

echo "── cluster: validate → import → plan → apply (as act-admin)"
( cd cluster
  omnigraph cluster validate
  if [ -f __cluster/state.json ]; then
      omnigraph cluster refresh      # existing state ledger → refresh
  else
      omnigraph cluster import       # first run → create initial state
  fi
  omnigraph cluster plan || true
  omnigraph cluster apply --as act-admin )

export OMNIGRAPH_SERVER_BEARER_TOKENS_JSON=$(python3 - <<'PY'
import json, os
print(json.dumps({
    "act-admin":    os.environ["TOK_ADMIN"],
    "act-reviewer": os.environ["TOK_REVIEWER"],
    "act-ingest":   os.environ["TOK_INGEST"],
    "act-content":  os.environ["TOK_CONTENT"],
    "act-gtm":      os.environ["TOK_GTM"],
}))
PY
)

# embedding provider must match what pipeline.ingest uses (mock is default)
export OMNIGRAPH_EMBED_PROVIDER="${OMNIGRAPH_EMBED_PROVIDER:-mock}"

echo "── serving on http://$BIND   (embed provider: $OMNIGRAPH_EMBED_PROVIDER)"
echo "   console: make app   ·   ingest: make ingest FILES=\"seed-data/*.md\""
exec omnigraph-server --cluster cluster --bind "$BIND"
