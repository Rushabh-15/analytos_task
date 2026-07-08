#!/bin/sh
# Boot sequence for the Omnigraph container.
# 1. Seed /data/cluster from the image's baked-in cluster on first boot.
# 2. validate → import → plan → apply (attributed to act-admin).
# 3. Serve. Bearer tokens come from OMNIGRAPH_SERVER_BEARER_TOKENS_JSON;
#    if unset we refuse to start unless OMNIGRAPH_UNAUTHENTICATED=1.
set -eu

CLUSTER_DIR="${CLUSTER_DIR:-/data/cluster}"
mkdir -p "$CLUSTER_DIR"
if [ ! -f "$CLUSTER_DIR/cluster.yaml" ]; then
    echo "▶ first boot — seeding cluster into $CLUSTER_DIR"
    cp -R /opt/cluster/. "$CLUSTER_DIR/"
else
    echo "▶ existing cluster found — refreshing schemas/queries/policies from image"
    # keep graph data, refresh declarative sources so redeploys pick up edits
    cp -R /opt/cluster/. "$CLUSTER_DIR/"
fi

cd "$CLUSTER_DIR"
echo "▶ omnigraph cluster validate"
omnigraph cluster validate
echo "▶ omnigraph cluster import"
omnigraph cluster import
echo "▶ omnigraph cluster plan"
omnigraph cluster plan || true
echo "▶ omnigraph cluster apply (as act-admin)"
omnigraph cluster apply --as act-admin

if [ -z "${OMNIGRAPH_SERVER_BEARER_TOKENS_JSON:-}" ]; then
    if [ "${OMNIGRAPH_UNAUTHENTICATED:-0}" = "1" ]; then
        echo "▶ serving UNAUTHENTICATED (local dev only)"
        exec omnigraph-server --cluster "$CLUSTER_DIR" \
            --bind "${OMNIGRAPH_BIND:-0.0.0.0:8080}" --unauthenticated
    fi
    echo "✘ OMNIGRAPH_SERVER_BEARER_TOKENS_JSON is not set." >&2
    echo "  Set it (see .env.example) or OMNIGRAPH_UNAUTHENTICATED=1 for local dev." >&2
    exit 1
fi

echo "▶ serving with bearer-token auth on ${OMNIGRAPH_BIND:-0.0.0.0:8080}"
exec omnigraph-server --cluster "$CLUSTER_DIR" --bind "${OMNIGRAPH_BIND:-0.0.0.0:8080}"
