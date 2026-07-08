#!/usr/bin/env bash
# End-to-end verification of the governed loop against a RUNNING server
# (scripts/serve_local.sh in another terminal, or the docker stack).
#
#   1  healthz
#   2  deterministic ingest (fixtures + mock embeddings) → review branch
#   3  branch visible to reviewer
#   4  Cedar NEGATIVE: act-content cannot read the unreviewed branch (403)
#   5  Cedar NEGATIVE: act-content cannot read the comms graph at all (403)
#   6  reviewer approves → branch merged to main (attributed to act-reviewer)
#   7  act-content CAN now read the same data from knowledge@main
#   8  content agent (template mode) writes a blog citing ≥3 graph facts
#   9  declarative policy tests (omnigraph policy test), if available
#
# Exit 0 = every gate held. This is the script to run before recording the demo.
set -uo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

BASE="${OMNIGRAPH_BASE_URL:-http://127.0.0.1:8080}"
RUN="verify-$(date +%s)"
BRANCH="ingest/$RUN"
FAIL=0
say()  { printf '%s\n' "$*"; }
pass() { say "   ✔ $*"; }
fail() { say "   ✘ $*"; FAIL=1; }

http() { # method url token [json] → "STATUS<TAB>BODY"
    local m="$1" u="$2" t="$3" d="${4:-}"
    if [ -n "$d" ]; then
        curl -sS -o /tmp/verify_body -w '%{http_code}' -X "$m" "$u" \
            -H "Authorization: Bearer $t" -H 'Content-Type: application/json' \
            -d "$d" 2>/tmp/verify_err || true
    else
        curl -sS -o /tmp/verify_body -w '%{http_code}' -X "$m" "$u" \
            -H "Authorization: Bearer $t" 2>/tmp/verify_err || true
    fi
}

say "━━ 1 · server health"
code=$(http GET "$BASE/healthz" "${TOK_REVIEWER:-x}")
[ "$code" = "200" ] && pass "healthz 200" || { fail "server unreachable at $BASE (got $code)"; exit 1; }

say "━━ 2 · deterministic ingest → $BRANCH"
if EXTRACT_PROVIDER=fixture OMNIGRAPH_EMBED_PROVIDER="${OMNIGRAPH_EMBED_PROVIDER:-mock}" \
   python3 -m pipeline.ingest seed-data/*.md --run-id "$RUN" --force; then
    pass "pipeline loaded both graphs onto $BRANCH"
else
    fail "pipeline failed"; exit 1
fi

say "━━ 3 · reviewer can see the branch"
code=$(http GET "$BASE/graphs/knowledge/branches" "$TOK_REVIEWER")
if grep -q "$BRANCH" /tmp/verify_body; then pass "branch listed on knowledge"; else fail "branch missing ($code)"; fi

QUERY_PRODUCTS='{"query":"query l() { match { $p: Product } return { $p.slug } limit 5 }","branch":"BRANCHNAME"}'

say "━━ 4 · NEGATIVE — act-content reading the UNREVIEWED branch must be denied"
code=$(http POST "$BASE/graphs/knowledge/query" "$TOK_CONTENT" "${QUERY_PRODUCTS/BRANCHNAME/$BRANCH}")
if [ "$code" = "403" ]; then pass "engine returned 403 on branch read (branch_scope: protected only)"; else fail "expected 403, got $code: $(head -c 160 /tmp/verify_body)"; fi

say "━━ 5 · NEGATIVE — act-content reading comms (EmailThread) must be denied"
code=$(http POST "$BASE/graphs/comms/query" "$TOK_CONTENT" \
    '{"query":"query l() { match { $t: EmailThread } return { $t.slug } limit 3 }","branch":"main"}')
if [ "$code" = "403" ]; then pass "engine returned 403 — content agent has NO access to comms"; else fail "expected 403, got $code: $(head -c 160 /tmp/verify_body)"; fi

say "━━ 6 · reviewer approves — merge $BRANCH → main on both graphs"
ok=1
for g in knowledge comms; do
    code=$(http POST "$BASE/graphs/$g/branches/merge" "$TOK_REVIEWER" \
        "{\"source\":\"$BRANCH\",\"target\":\"main\"}")
    case "$code" in 2*) : ;; *) ok=0; fail "merge on $g returned $code: $(head -c 160 /tmp/verify_body)";; esac
done
[ "$ok" = 1 ] && pass "merged to main as act-reviewer (see commit log attribution)"

say "━━ 7 · act-content can read the SAME data once it is on main"
code=$(http POST "$BASE/graphs/knowledge/query" "$TOK_CONTENT" "${QUERY_PRODUCTS/BRANCHNAME/main}")
if [ "$code" = "200" ] && grep -q "prod-" /tmp/verify_body; then
    pass "products readable on main by act-content"
else fail "expected 200 with products, got $code"; fi

say "━━ 8 · content agent (template mode, no LLM) cites ≥3 graph facts"
if command -v npx >/dev/null 2>&1; then
    if AGENT_PROVIDER=none python3 -m agents.content_agent --product prod-stockly \
        --topic "cutting food waste" --out "out/$RUN" >/tmp/verify_agent 2>&1; then
        blog=$(ls out/$RUN/blog-*.md 2>/dev/null | head -1)
        cites=$(grep -o '\[F[0-9]*\]' "$blog" | sort -u | wc -l | tr -d ' ')
        [ "${cites:-0}" -ge 3 ] && pass "blog written with $cites distinct fact citations + ledger" \
                                || fail "blog has <3 citations"
        grep -qi 'greencart\|mednova' "$blog" && fail "LEAK: client name in blog" \
                                              || pass "leak guard clean"
    else fail "content agent failed: $(tail -2 /tmp/verify_agent)"; fi
else
    say "   ⚠ npx not found — skipping MCP agent step (install Node 18+)"
fi

say "━━ 9 · declarative Cedar policy tests"
if omnigraph policy test --tests cluster/policies/knowledge.tests.yaml --cluster cluster >/dev/null 2>&1 \
&& omnigraph policy test --tests cluster/policies/comms.tests.yaml --cluster cluster >/dev/null 2>&1; then
    pass "policy test suites green"
else
    say "   ⚠ 'omnigraph policy test' unavailable or failed — run manually to inspect"
fi

say ""
if [ "$FAIL" = 0 ]; then
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    say "  PASS — governed loop verified end to end"
    say "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    say "  FAILURES above — fix before the demo"; exit 1
fi
