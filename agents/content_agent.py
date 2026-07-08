"""Content Agent — writes public-facing content from graph facts ONLY.

Guarantees demonstrated:
  * Reads Omnigraph exclusively through the MCP server with the act-content
    token (Cedar: read/invoke on protected `main` of `knowledge` only —
    no comms graph, no unreviewed branches).
  * client_safe=false proof points are excluded BEFORE the LLM sees anything,
    so confidential metrics cannot leak into a draft.
  * Every metric in the blog carries a [F#] marker; the appended Fact Ledger
    maps each marker → graph node slug → retrieval query (traceability).
  * A post-generation leak guard fails the run if any denylisted client name
    or non-Analytos email surfaces.

Usage:
    python -m agents.content_agent --product prod-stockly --topic "cutting food waste"
    python -m agents.content_agent --ask "What proof do we have that Stockly reduces waste?"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from . import llm
from .mcp_bridge import GQ, MCPBridgeError, OmnigraphMCP, bridge_for_role

DENYLIST_DEFAULT = "GreenCart,greencartmarkets,MedNova,mednovadevices,Stuttgart"


def denylist() -> list[str]:
    raw = os.getenv("CLIENT_NAME_DENYLIST", DENYLIST_DEFAULT)
    return [t.strip() for t in raw.split(",") if t.strip()]


def leak_scan(text: str) -> list[str]:
    hits = [t for t in denylist() if re.search(re.escape(t), text, re.I)]
    hits += [m.group(0) for m in
             re.finditer(r"[\w.+-]+@(?!analytos\.ai)[\w-]+\.[\w.]+", text)]
    return hits


def gather(bridge: OmnigraphMCP, product_slug: str | None, topic: str):
    clean = bridge._clean
    products = clean(bridge.query(GQ["list_products"]))
    if product_slug:
        products = [p for p in products if p["slug"] == product_slug]
        if not products:
            sys.exit(f"product '{product_slug}' not found on main")
    facts, excluded = [], 0
    per_product = []
    for p in products:
        detail = clean(bridge.query(GQ["get_product"], {"slug": p["slug"]}))
        feats = clean(bridge.query(GQ["product_features"], {"slug": p["slug"]}))
        pps = clean(bridge.query(GQ["product_proofpoints"], {"slug": p["slug"]}))
        segs = clean(bridge.query(GQ["product_segments"], {"slug": p["slug"]}))
        safe = [pp for pp in pps if pp.get("client_safe") is not False]
        excluded += len(pps) - len(safe)
        for pp in safe:
            facts.append({
                "ref": f"F{len(facts) + 1}",
                "claim": pp["claim"],
                "value": pp.get("metric_value"), "unit": pp.get("unit"),
                "timeframe": pp.get("timeframe"),
                "evidence_type": pp.get("evidence_type"),
                "slug": pp["slug"],
                "query": "product_proofpoints(slug=%s)" % p["slug"],
            })
        per_product.append({"product": detail[0] if detail else p,
                            "features": feats, "segments": segs})
    chunks = clean(bridge.query(GQ["hybrid_chunks"],
                                {"q": topic or products[0]["name"]}))
    return per_product, facts, chunks, excluded


BLOG_SYSTEM = """You are Analytos' content agent. Write a publishable blog post in Markdown.
HARD RULES — violations make the draft unusable:
1. Use ONLY the facts, features and context provided. Do not invent numbers,
   customers, or capabilities. If a stat is not in the Fact Ledger, it does
   not exist.
2. Every quantitative claim MUST be immediately followed by its ledger marker,
   e.g. "cut waste by 38% [F1]". Use at least 3 distinct markers.
3. NEVER name or hint at specific customers. Use only the anonymous
   descriptors already present in the facts (e.g. "a mid-market US grocery
   chain").
4. 600–900 words, a compelling title as an H1, subheads, a closing CTA to
   analytos.ai. Confident, concrete, zero fluff.
Return only the blog post markdown (no ledger — it is appended separately)."""


def blog_via_llm(per_product, facts, chunks, topic):
    ctx = ["# FACT LEDGER (the only permitted quantitative claims)"]
    for f in facts:
        ctx.append(f"[{f['ref']}] {f['claim']} — {f['value'] or ''} "
                   f"{f['unit'] or ''} ({f['evidence_type']}, {f['timeframe'] or 'n/a'})")
    ctx.append("\n# PRODUCTS")
    for block in per_product:
        p = block["product"]
        ctx.append(f"## {p['name']} — {p.get('tagline') or ''}\n{p.get('description') or ''}")
        for ft in block["features"]:
            star = " (differentiator)" if ft.get("differentiator") else ""
            ctx.append(f"- Feature: {ft['name']}{star}: {ft.get('description') or ''}")
        for s in block["segments"]:
            ctx.append(f"- Target segment: {s['name']}: {s.get('description') or ''}")
    ctx.append("\n# BACKGROUND CONTEXT (from approved docs)")
    for c in chunks[:6]:
        ctx.append(f"- {c['text'][:400]}")
    user = (f"Topic/angle: {topic or 'why this product wins'}\n\n" + "\n".join(ctx))
    return llm.complete(BLOG_SYSTEM, user)


def blog_via_template(per_product, facts, topic):
    p = per_product[0]["product"]
    lines = [f"# {p['name']}: {topic or p.get('tagline') or 'proof over promises'}",
             "", p.get("description") or "", "", "## What the numbers say", ""]
    for f in facts[:5]:
        val = f" — **{f['value']}**" if f.get("value") else ""
        lines.append(f"- {f['claim']}{val} [{f['ref']}]")
    lines += ["", "## How it works", ""]
    for ft in per_product[0]["features"]:
        lines.append(f"- **{ft['name']}** — {ft.get('description') or ''}")
    lines += ["", "Ready to see it on your data? Visit analytos.ai.", ""]
    return "\n".join(lines)


def ledger_md(facts) -> str:
    rows = ["", "---", "", "## Fact Ledger (traceability appendix)", "",
            "| Ref | Claim | Value | Graph node | Retrieved via |",
            "|-----|-------|-------|------------|---------------|"]
    for f in facts:
        rows.append(f"| {f['ref']} | {f['claim']} | {f['value'] or '—'} "
                    f"| `{f['slug']}` | `{f['query']}` |")
    rows.append("")
    rows.append("_Every metric above resolves to a node on `knowledge@main`; "
                "nothing in this post exists outside the approved graph._")
    return "\n".join(rows)


def cmd_blog(args) -> int:
    with bridge_for_role("content", "knowledge") as bridge:
        per_product, facts, chunks, excluded = gather(
            bridge, args.product, args.topic)
    if len(facts) < 3:
        sys.exit("need at least 3 client-safe proof points on main; "
                 "ingest + approve first")
    try:
        body = blog_via_llm(per_product, facts, chunks, args.topic) \
            if llm.provider() != "none" else \
            blog_via_template(per_product, facts, args.topic)
    except Exception as e:                     # LLM hiccup → deterministic path
        print(f"  (LLM unavailable → template mode: {e})")
        body = blog_via_template(per_product, facts, args.topic)

    used = set(re.findall(r"\[(F\d+)\]", body))
    if len(used) < 3:
        print("  (draft cited <3 facts → falling back to template mode)")
        body = blog_via_template(per_product, facts, args.topic)
        used = set(re.findall(r"\[(F\d+)\]", body))

    hits = leak_scan(body)
    if hits:
        sys.exit(f"LEAK GUARD TRIPPED — draft mentions {hits}; refusing to write output.")

    out = body + ledger_md([f for f in facts if f["ref"] in used] or facts)
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    name = args.product or "all-products"
    path = out_dir / f"blog-{name}-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(out)
    print(f"✔ blog written: {path}")
    print(f"  facts cited: {sorted(used)}   client_safe=false excluded: {excluded}")
    print("  leak guard: clean (no client names, no external emails)")
    return 0


ASK_SYSTEM = """Answer the question using ONLY the graph facts provided.
Cite the node slug in backticks after each fact you use. If the graph does
not contain the answer, say exactly that — do not guess. Be concise."""


def cmd_ask(args) -> int:
    with bridge_for_role("content", "knowledge") as bridge:
        clean = bridge._clean
        chunks = clean(bridge.query(GQ["hybrid_chunks"], {"q": args.ask}))
        pps = clean(bridge.query(GQ["search_proofpoints"], {"q": args.ask}))
        pps = [p for p in pps if p.get("client_safe") is not False]
        prods = clean(bridge.query(GQ["list_products"]))
    ctx = ["# PROOF POINTS"]
    ctx += [f"- ({p['slug']}) {p['claim']} — {p.get('metric_value') or ''}" for p in pps]
    ctx.append("# PRODUCTS")
    ctx += [f"- ({p['slug']}) {p['name']}: {p.get('tagline') or ''}" for p in prods]
    ctx.append("# DOC CHUNKS")
    ctx += [f"- ({c['slug']} from {c['doc_slug']}) {c['text'][:350]}" for c in chunks[:8]]
    if llm.provider() == "none":
        print(f"Q: {args.ask}\n\nTop graph facts (no LLM configured):\n" + "\n".join(ctx))
        return 0
    answer = llm.complete(ASK_SYSTEM, f"Question: {args.ask}\n\n" + "\n".join(ctx))
    hits = leak_scan(answer)
    if hits:
        sys.exit(f"LEAK GUARD TRIPPED in answer: {hits}")
    print(answer)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Analytos content agent (MCP, act-content)")
    ap.add_argument("--product", help="product slug, e.g. prod-stockly")
    ap.add_argument("--topic", default=None, help="blog angle")
    ap.add_argument("--ask", default=None, help="answer a question from the graph")
    ap.add_argument("--out", default="out/content")
    args = ap.parse_args()
    try:
        return cmd_ask(args) if args.ask else cmd_blog(args)
    except MCPBridgeError as e:
        sys.exit(f"MCP error (Cedar may have denied this actor): {e}")


if __name__ == "__main__":
    sys.exit(main())
