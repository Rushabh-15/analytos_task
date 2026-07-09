#!/bin/sh
# Single-service boot for Render: Omnigraph (127.0.0.1:8080) + console ($PORT).
set -eu

CLUSTER_SRC=/srv/cluster
CLUSTER_DIR="${CLUSTER_DIR:-/data/cluster}"
mkdir -p "$CLUSTER_DIR"

# seed / refresh declarative cluster (schemas, queries, policies) into the disk
cp -R "$CLUSTER_SRC"/. "$CLUSTER_DIR"/

cd "$CLUSTER_DIR"
echo "▶ applying cluster (as act-admin)"
omnigraph cluster validate
omnigraph cluster import
omnigraph cluster plan || true
omnigraph cluster apply --as act-admin

# bearer tokens for the graph (must be set in Render env)
: "${TOK_ADMIN:?set TOK_ADMIN in Render env}"
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
export OMNIGRAPH_EMBED_PROVIDER="${OMNIGRAPH_EMBED_PROVIDER:-mock}"

echo "▶ starting Omnigraph on 127.0.0.1:8080"
omnigraph-server --cluster "$CLUSTER_DIR" --bind 127.0.0.1:8080 &
OG_PID=$!

# wait for health before starting the console
echo "▶ waiting for Omnigraph health…"
for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
        echo "  ✔ Omnigraph healthy"; break
    fi
    if ! kill -0 "$OG_PID" 2>/dev/null; then
        echo "✘ Omnigraph exited during startup"; exit 1
    fi
    sleep 2
done

# console talks to Omnigraph on localhost; Render provides $PORT
export OMNIGRAPH_BASE_URL="http://127.0.0.1:8080"
export OMNIGRAPH_TOKEN_REVIEWER="${TOK_REVIEWER}"
PORT="${PORT:-8000}"
echo "▶ starting review console on 0.0.0.0:$PORT"
cd /srv
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"