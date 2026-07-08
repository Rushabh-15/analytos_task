# Analytos Brain — a governed org-context layer on Omnigraph

A proof-of-concept "company brain" for Analytos: product docs, ICP notes and
client email threads are LLM-extracted into a **versioned, policy-gated
knowledge graph** ([Omnigraph](https://github.com/ModernRelay/omnigraph)),
reviewed by a human before anything goes live, and consumed by two AI agents
through **MCP with per-role Cedar enforcement** — so the content agent can
quote a pilot metric but can never see the email it came from.

```
                       ┌─ HITL review console (FastAPI + web UI) ─┐
                       │   diff vs main · approve = merge · reject │
                       │   = discard · commits attributed to actor │
                       └───────────────▲──────────────────────────┘
                                       │ act-reviewer (only role that can
                                       │ merge into protected main)
 seed docs ──▶ pipeline ──▶ LLM extract ──▶ load onto branch ingest/<run>
 (md files)    (python)     (strict JSON,     │
                            anonymization)    ▼
                     ┌──────────── Omnigraph cluster ────────────┐
                     │  graph: knowledge          graph: comms   │
                     │  products·features·proof   email threads  │
                     │  points·ICP·personas·      messages·      │
                     │  decisions·chunks(vec)     participants   │
                     │        Cedar policies (default-deny)      │
                     └───────▲───────────────────────▲───────────┘
                             │ act-content, act-gtm  │ act-reviewer only
                             │ (read main only)      │ (no agent role at all)
                     ┌───────┴───────┐       ┌───────┴────────┐
                     │ Content agent │       │  (agents get   │
                     │ GTM agent     │       │   engine 403)  │
                     │ via MCP srvr  │       └────────────────┘
                     └───────────────┘
```

Everything an agent "knows" is a node on `knowledge@main` — which only exists
because a human pressed **Approve**.

## The governed loop

1. **Ingest** — `python -m pipeline.ingest <files>` computes a sha256 per doc
   (already-ingested files are skipped → idempotent re-runs), calls the LLM
   extractor (strict-JSON, pydantic-validated), and loads nodes/edges onto a
   fresh branch `ingest/<run>` forked from `main` on both graphs. The loader
   runs as **act-ingest**, which Cedar allows to create/write *unprotected*
   branches only — it cannot touch `main`.
2. **Extract** — one typed `ExtractionResult` per doc: products, features,
   structured proof points (`metric_name/value/unit/timeframe/evidence_type`
   + a `client_safe` flag), ICP segments, personas, competitors, decisions,
   people, full email threads. The prompt **anonymizes client names** in all
   claims/decisions; anything unavoidably identifying is flagged
   `client_safe=false`.
3. **Review** — the console shows a field-level diff of the branch vs `main`
   (volatile timestamps ignored). **Approve** merges branch → `main` on both
   graphs *as act-reviewer* — `main` is a protected branch and act-reviewer
   holds the only `branch_merge → protected` grant, so the human click *is*
   the security boundary, not a UI convention. **Reject** deletes the branch;
   nothing reaches `main`. Every commit carries its actor.
4. **Serve** — dashboard: entity browser for every type, hybrid search
   (RRF of vector `nearest` + `bm25`, plus entity full-text), thread viewer,
   commit activity feed.
5. **Agents** — both run over stdio MCP (`npx @modernrelay/omnigraph-mcp`)
   with their own bearer token, so the engine authorizes **every** read:
   * **Content agent** → blog posts / Q&A. `client_safe=false` proof is
     excluded before the LLM sees context; each metric carries an `[F#]`
     marker resolved in an appended Fact Ledger (claim → node slug → query);
     a leak guard fails the run if a denylisted client name or non-Analytos
     email appears.
   * **GTM agent** → prospecting briefs: ICP definition, buying committee &
     objections, trigger signals, competitor displacement angles, a proof kit
     split *quotable vs internal-only*, anonymized recent momentum, and
     3 clearly-illustrative example target companies.

## Quickstart (local, no keys needed)

Prereqs: Linux/macOS, Python 3.10+, Node 18+ (for the MCP server), `curl`.

```bash
git clone <this-repo> && cd analytos-brain
scripts/bootstrap.sh          # installs omnigraph binaries + python deps, creates .env
$EDITOR .env                  # paste real tokens (openssl rand -hex 24) + console password

make serve                    # terminal 1 — apply cluster, serve Omnigraph :8080
make app                      # terminal 2 — review console → http://127.0.0.1:8000
make ingest-fixture           # terminal 3 — deterministic ingest (no API keys)
```

Open the console → **Review** → inspect the diff → **Approve**. Then:

```bash
make blog                     # content agent → out/content/blog-…md (+ Fact Ledger)
make brief                    # gtm agent     → out/gtm/brief-…md
make negative-demo            # engine-level 403: content agent vs comms graph
make verify                   # scripted e2e incl. both Cedar negative tests
```

The keyless path uses `EXTRACT_PROVIDER=fixture` (pre-baked extractions in
`fixtures/`) and `OMNIGRAPH_EMBED_PROVIDER=mock`. For the real thing, set
`ANTHROPIC_API_KEY` (or OpenAI/Gemini) in `.env`, remove
`EXTRACT_PROVIDER=fixture`, and optionally switch both embed sides to a real
provider — see `.env.example`. **The sample files in `seed-data/` are
stand-ins**; drop the real task-pack files over them (same names) and rerun
`make ingest`.

## Access-control model

| Actor (token) | knowledge | comms | Can merge to main? |
|---|---|---|---|
| `act-admin` | everything | everything | yes (ops only) |
| `act-reviewer` | read any branch, merge/delete branches | same | **yes — the approval gate** |
| `act-ingest` | create + write **unprotected** branches, read | same | no |
| `act-content` | read + query **main only** | **nothing — no rule exists** | no |
| `act-gtm` | read + query + export **main only** | **nothing** | no |

Two design choices make the guarantees structural rather than behavioral:

* **Two graphs, one cluster.** Omnigraph policies are per-graph, so raw
  comms (EmailThread/EmailMessage) live in their own graph where no agent
  group appears in any rule. Default-deny does the rest: the content agent's
  token gets an engine 403 on *any* comms request — provably, via
  `make negative-demo` and `scripts/verify_e2e.sh` step 5. Distilled,
  anonymized knowledge (decisions, proof points) crosses into `knowledge`
  through the reviewed pipeline; soft slug refs (`Decision.thread_ref`)
  let a human trace provenance back without granting agents a path in.
* **Protected `main` + branch-scoped grants.** Agents may read only
  `main`; ingest may write only non-`main`; only the reviewer may merge into
  protected branches. Unreviewed extractions are therefore *unreachable* by
  agents (verify step 4), and the approve click maps 1:1 to the only
  permitted state transition.

Declarative Cedar tests live in `cluster/policies/*.tests.yaml`
(`make policy-test`).

## Design decisions worth knowing

1. **Idempotent ingest** — sha256 short-circuit per doc, deterministic slugs,
   `--mode merge` upserts on `@key`, and every edge is `@unique(src, dst)`:
   re-ingesting the same file is a no-op, revised files produce a clean
   *changed-fields* diff instead of duplicates.
2. **Embeddings computed in the pipeline**, not via schema `@embed`, so
   branch merges can never serve stale vectors and the provider is pinned in
   one place; the server embeds only query strings at search time with the
   same `OMNIGRAPH_EMBED_*` config (one vector space, mock by default).
3. **Chunks come only from product/ICP docs.** Emails are never chunked or
   embedded into `knowledge` — retrieval can't leak a thread by similarity.
4. **`client_safe` at extraction + exclusion before generation + leak-guard
   after generation.** Three independent layers between a confidential
   number and a published blog.
5. **Attribution everywhere** — pipeline loads as act-ingest, approvals merge
   as act-reviewer, agents read as themselves; the Activity tab is a true
   audit log of *who did what to the graph*.
6. **Fixture + mock + template modes** — the entire loop runs with zero API
   keys and zero network flakiness; real LLMs are a `.env` change. Demos
   shouldn't gamble.

## Evaluation-criteria map

| Criterion | Where it lives |
|---|---|
| Governance & review (25%) | branch-per-ingest (`pipeline/ingest.py`), protected-main Cedar gate (`cluster/policies/*`), diff/approve/reject console (`app/`), actor-attributed commits, `scripts/verify_e2e.sh` |
| Extraction quality (20%) | `pipeline/prompts.py` (typed schema, structured metrics, anonymization), `pipeline/model.py`, per-doc fixtures |
| Agent output (20%) | `agents/content_agent.py` (Fact Ledger, ≥3 cited metrics), `agents/gtm_agent.py` (full brief incl. 3 illustrative targets), `--ask` mode for unseen questions |
| Access control (15%) | two-graph split, role tokens, `cluster/policies/`, `agents/negative_demo.py`, verify steps 4–5, policy test suites |
| Dashboard (10%) | `app/static/index.html` — browser, hybrid search, review, activity |
| Hygiene (10%) | this README, Makefile, `.env.example`, scripts, fixtures, `.gitignore` |

## 5-minute demo runbook

1. *(30s)* Architecture slide = the ASCII above: two graphs, five actors,
   one protected branch.
2. *(60s)* `make ingest FILES="seed-data/*.md"` → console **Review** →
   walk the diff (green adds, amber field changes) → **Approve** → Activity
   tab shows the merge commit *as act-reviewer*.
3. *(60s)* Browse: open Stockly → features/proof points (point at the red
   `client_safe=false` badge) → Search "waste reduction pilot" → hybrid
   chunk + proof-point hits.
4. *(90s)* `make blog` → open the post: metrics with `[F#]` → Fact Ledger
   maps to slugs. `make brief` → show quotable-vs-internal proof kit + the
   3 illustrative targets. Then the kill shot: `make negative-demo` →
   engine 403 for content-agent on comms.
5. *(60s)* Evaluator's live doc: `scripts/demo_day.sh their-doc.md` →
   review → approve → `make ask-content Q="…"` / `make ask-gtm Q="…"`.

## Hosting

`deploy/HOSTING.md` — docker-compose for any VPS (one command) and a Railway
recipe. Submission needs: console URL + basic-auth creds, Omnigraph URL +
the two agent tokens (so the evaluator can attach their own MCP client using
`agents/claude_desktop_config.example.json`).

## Repo layout

```
cluster/            cluster.yaml, knowledge.pg, comms.pg
  queries/          stored .gq (products, gtm, decisions, search, provenance)
  queries-comms/    thread queries (reviewer-facing)
  policies/         Cedar YAML per graph + declarative test suites
pipeline/           ingest CLI, LLM extractors, embeddings, HTTP client
fixtures/           deterministic extractions for keyless demo mode
seed-data/          SAMPLE stand-ins — replace with the real task files
app/                FastAPI review console + single-file UI
agents/             MCP bridge, content agent, gtm agent, negative demo
deploy/             Dockerfiles, compose, hosting notes
scripts/            bootstrap, serve, verify_e2e, demo_day
```

## Troubleshooting

* **Schema/query edits not visible** → rerun `make serve`; applied cluster
  changes are served after restart.
* **Merge 504 / slow first query** → cold caches; retry once. The console
  surfaces the raw engine error text on any failure.
* **`nearest()` returns odd results** → pipeline and server must share
  `OMNIGRAPH_EMBED_PROVIDER/MODEL`. Re-ingest after changing providers
  (vectors are stored per chunk).
* **Agent errors mentioning 403** → that's Cedar working; check which token
  the bridge got. `make negative-demo` shows the intended denial shape.
* **Stale `ingest/*` branches** → reject them in the console (deletes), or
  `curl -X DELETE $BASE/graphs/<g>/branches/<name>` as act-reviewer.

## What I'd build next

Webhook/inbox ingestion instead of CLI; reviewer edits-before-approve
(mutate on the branch, then merge); per-field provenance chips in the UI
(every value → source chunk highlight); embedding-provider migration job;
rejected-branch archive for extractor eval sets; OpenTelemetry on the
pipeline.
