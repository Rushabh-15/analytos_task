#!/usr/bin/env bash
# One-time setup on a dev machine (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "── 1/3 · Omnigraph binaries"
if command -v omnigraph >/dev/null 2>&1; then
    echo "   already installed: $(omnigraph --version 2>/dev/null || true)"
else
    curl -fsSL https://raw.githubusercontent.com/ModernRelay/omnigraph/main/scripts/install.sh | sh
    command -v omnigraph >/dev/null || {
        echo "   installer finished but 'omnigraph' is not on PATH — open a new shell or add the printed dir to PATH"; exit 1; }
fi

echo "── 2/3 · Python deps"
python3 -m pip install -r requirements.txt --quiet \
    || python3 -m pip install -r requirements.txt --break-system-packages --quiet
echo "   ok"

echo "── 3/3 · Node (for the MCP server the agents spawn)"
if command -v npx >/dev/null 2>&1; then
    echo "   npx found: $(node --version)"
else
    echo "   ⚠ npx not found — install Node 18+ before running agents (pipeline/console work without it)"
fi

[ -f .env ] || { cp .env.example .env; echo "▶ created .env from .env.example — edit tokens before serving"; }
echo "✔ bootstrap complete. Next: scripts/serve_local.sh"
