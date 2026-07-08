#!/usr/bin/env bash
# Demo day: the evaluator hands you a NEW document. This ingests it with the
# real LLM extractor onto its own review branch, then tells you what to do.
#   scripts/demo_day.sh path/to/new-doc.md
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

[ $# -ge 1 ] || { echo "usage: scripts/demo_day.sh <file.md> [more files…]"; exit 1; }

if [ "${EXTRACT_PROVIDER:-}" = "fixture" ] || { [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${GEMINI_API_KEY:-}" ]; }; then
    echo "⚠ no real LLM configured (EXTRACT_PROVIDER/keys) — a live doc needs one." >&2
    exit 1
fi

RUN="live-$(date +%H%M%S)"
python3 -m pipeline.ingest "$@" --run-id "$RUN"

cat <<EOF

▶ Extracted onto branch ingest/$RUN — nothing is live yet.
  1. Open the console → Review → ingest/$RUN → inspect the diff.
  2. Approve (merges to main as act-reviewer) or Reject (discards).
  3. Re-ask the agents; the new facts are now theirs:
       python3 -m agents.content_agent --ask "…"
       python3 -m agents.gtm_agent     --ask "…"
EOF
