# Hosting the demo

Two public URLs are needed for the submission:

| URL | What | Auth |
|-----|------|------|
| `https://<omnigraph-host>` | Omnigraph HTTP API (agents + MCP) | Bearer tokens (`TOK_*`) |
| `https://<console-host>` | Review console | HTTP Basic (`APP_USER`/`APP_PASSWORD`) |

## Option A — any VPS with Docker (simplest, ~10 min)

```bash
git clone <your-repo> && cd analytos-brain
cp .env.example .env            # fill in tokens + APP_PASSWORD (+ LLM key)
docker compose --env-file .env -f deploy/docker-compose.yml up --build -d
```

Put both ports behind your reverse proxy / Caddy / Cloudflare tunnel for TLS.
The Omnigraph container refuses to boot without bearer tokens, so nothing is
ever exposed unauthenticated.

Ingest runs from your laptop against the hosted server:

```bash
export OMNIGRAPH_BASE_URL=https://<omnigraph-host>
make ingest FILES="seed-data/*.md"
```

## Option B — Railway

Upstream recipe: `ModernRelay/omnigraph → docs/user/deployment.md` and
`omnigraph-cookbooks/railway.toml`. For this repo:

1. Create a Railway project from the GitHub repo. Add **two services**:
   * `omnigraph` — Dockerfile path `deploy/Dockerfile.server`, attach a
     **volume** mounted at `/data`, expose port `8080`.
   * `console` — Dockerfile path `deploy/Dockerfile.app`, expose port `8000`.
2. Set variables on `omnigraph`:
   * `OMNIGRAPH_SERVER_BEARER_TOKENS_JSON` = the JSON from `.env.example`
     with your real tokens
   * `OMNIGRAPH_EMBED_PROVIDER` (+ `GEMINI_API_KEY` or OpenAI-compatible
     vars) — must match what the pipeline uses, or leave `mock`
3. Set variables on `console`:
   * `OMNIGRAPH_BASE_URL` = the omnigraph service's **private** URL
     (e.g. `http://omnigraph.railway.internal:8080`)
   * `OMNIGRAPH_TOKEN_REVIEWER`, `APP_USER`, `APP_PASSWORD`
4. Generate public domains for both services. Give the evaluator the console
   URL + basic-auth creds, and (optionally) the omnigraph URL + the
   `act-content` / `act-gtm` tokens so they can point their own MCP client at
   it (`agents/claude_desktop_config.example.json`).

## Embeddings in production

Vectors are computed by the **pipeline** at ingest time and by the **server**
at query time (`nearest($c.embedding, $q)` embeds the query string). Both
sides must therefore use the same provider + model: set
`OMNIGRAPH_EMBED_PROVIDER/MODEL` identically in the server environment and in
the shell that runs `pipeline.ingest`. `mock` is deterministic and keyless —
fine for the demo; switch both sides to `gemini` or an OpenAI-compatible
endpoint for real semantic quality.

## Demo-day live ingest

The evaluator hands you a new doc:

```bash
export OMNIGRAPH_BASE_URL=https://<omnigraph-host>   # plus tokens from .env
scripts/demo_day.sh path/to/new-doc.md
```

then approve it in the console and re-ask the agents.
