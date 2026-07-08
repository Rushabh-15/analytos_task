"""GTM Agent — builds a prospecting brief from the governed graph.

Reads through MCP with the act-gtm token (Cedar: read/invoke/export on
protected `main` of `knowledge`; comms remains invisible). The brief covers:
ICP definition, personas with objections, trigger signals, competitor
displacement angles, a proof kit split into externally-quotable
(client_safe=true) vs internal-only metrics, and 3 illustrative example
companies matched to the segment.

Usage:
    python -m agents.gtm_agent --segment seg-mid-market-grocery-convenience-retail
    python -m agents.gtm_agent                       # brief for every segment
    python -m agents.gtm_agent --ask "Which triggers should SDRs watch for?"
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from . import llm
from .content_agent import leak_scan
from .mcp_bridge import GQ, MCPBridgeError, bridge_for_role


def gather(bridge, segment_slug: str | None):
    clean = bridge._clean
    segments = clean(bridge.query(GQ["list_segments"]))
    if segment_slug:
        segments = [s for s in segments if s["slug"] == segment_slug]
        if not segments:
            sys.exit(f"segment '{segment_slug}' not found on main")
    out = []
    for seg in segments:
        personas = clean(bridge.query(GQ["segment_personas"], {"slug": seg["slug"]}))
        products = clean(bridge.query(GQ["segment_products"], {"slug": seg["slug"]}))
        proof, competitors, decisions = [], [], []
        for p in products:
            pps = clean(bridge.query(GQ["product_proofpoints"], {"slug": p["slug"]}))
            for pp in pps:
                pp["_product"] = p["name"]
            proof += pps
            comps = clean(bridge.query(GQ["product_competitors"], {"slug": p["slug"]}))
            for c in comps:
                c["_product"] = p["name"]
            competitors += comps
            decisions += clean(bridge.query(GQ["decisions_about_product"],
                                            {"slug": p["slug"]}))
        out.append({"segment": seg, "personas": personas, "products": products,
                    "proof": proof, "competitors": competitors,
                    "decisions": decisions})
    return out


BRIEF_SYSTEM = """You are Analytos' GTM agent. Produce a sharp SDR prospecting
brief in Markdown from the supplied graph facts ONLY.
HARD RULES:
1. No invented metrics — quote figures only from QUOTABLE PROOF; cite the node
   slug in backticks after each, e.g. (`proof-stockly-1a2b3c4d`).
2. INTERNAL-ONLY PROOF may inform positioning but must appear under a clearly
   marked "Internal only — do not quote externally" list, with slugs.
3. Never name real customers. Recent-win momentum may only use the anonymous
   decision summaries provided.
4. "Example target companies": exactly 3, clearly labelled ILLUSTRATIVE,
   invented to fit the segment definition (industry, size, geography,
   trigger). Give each a one-line "why now" tied to a trigger signal.
5. Sections: Segment definition · Buying committee & objections ·
   Trigger signals to monitor · Competitive displacement · Proof kit ·
   Recent momentum (anonymized) · 3 example target companies (illustrative) ·
   Suggested opening message. Be specific and skimmable."""


def brief_via_llm(block) -> str:
    seg = block["segment"]
    ctx = [f"# SEGMENT\n{seg['name']}: {seg.get('description') or ''}",
           f"industries={seg.get('industries')} size={seg.get('company_size')} "
           f"geo={seg.get('geographies')}",
           f"tech_signals={seg.get('tech_stack_signals')}",
           f"triggers={seg.get('trigger_signals')}",
           f"pains={seg.get('pain_points')} disqualifiers={seg.get('disqualifiers')}",
           "# PRODUCTS"]
    ctx += [f"- {p['name']}: {p.get('tagline') or ''}" for p in block["products"]]
    ctx.append("# PERSONAS")
    for per in block["personas"]:
        ctx.append(f"- {per['title']} ({per.get('buying_role')}): goals={per.get('goals')} "
                   f"objections={per.get('objections')}")
    ctx.append("# QUOTABLE PROOF (client_safe=true)")
    for pp in block["proof"]:
        if pp.get("client_safe") is not False:
            ctx.append(f"- ({pp['slug']}) [{pp['_product']}] {pp['claim']} — "
                       f"{pp.get('metric_value') or ''} {pp.get('unit') or ''} "
                       f"({pp.get('evidence_type')})")
    ctx.append("# INTERNAL-ONLY PROOF (client_safe=false — never quote externally)")
    for pp in block["proof"]:
        if pp.get("client_safe") is False:
            ctx.append(f"- ({pp['slug']}) [{pp['_product']}] {pp['claim']}")
    ctx.append("# COMPETITORS")
    for c in block["competitors"]:
        ctx.append(f"- ({c['slug']}) [{c['_product']}] {c['name']}: {c.get('notes') or ''} "
                   f"→ angle: {c.get('displacement_angle') or ''}")
    ctx.append("# RECENT DECISIONS (already anonymized)")
    for d in block["decisions"]:
        ctx.append(f"- ({d['slug']}) {d['summary']} [{d.get('status')}]")
    return llm.complete(BRIEF_SYSTEM, "\n".join(ctx), max_tokens=4000)


def brief_via_template(block) -> str:
    seg, L = block["segment"], []
    L += [f"# Prospecting brief — {seg['name']}", "",
          f"**Products:** {', '.join(p['name'] for p in block['products'])}", "",
          "## Segment definition", seg.get("description") or "",
          f"- Industries: {', '.join(seg.get('industries') or [])}",
          f"- Size: {seg.get('company_size') or '—'}",
          f"- Geography: {', '.join(seg.get('geographies') or [])}",
          f"- Disqualify: {', '.join(seg.get('disqualifiers') or [])}",
          "", "## Buying committee & objections"]
    for per in block["personas"]:
        L.append(f"- **{per['title']}** ({per.get('buying_role') or 'role n/a'}) — "
                 f"objections: {', '.join(per.get('objections') or []) or '—'}")
    L += ["", "## Trigger signals to monitor"]
    L += [f"- {t}" for t in (seg.get("trigger_signals") or [])]
    L += ["", "## Competitive displacement"]
    for c in block["competitors"]:
        L.append(f"- vs **{c['name']}** ({c['_product']}): "
                 f"{c.get('displacement_angle') or c.get('notes') or ''} (`{c['slug']}`)")
    L += ["", "## Proof kit — quotable (client_safe=true)"]
    for pp in block["proof"]:
        if pp.get("client_safe") is not False:
            L.append(f"- {pp['claim']} — **{pp.get('metric_value') or ''}** (`{pp['slug']}`)")
    internal = [pp for pp in block["proof"] if pp.get("client_safe") is False]
    if internal:
        L += ["", "## Internal only — do not quote externally"]
        L += [f"- {pp['claim']} (`{pp['slug']}`)" for pp in internal]
    if block["decisions"]:
        L += ["", "## Recent momentum (anonymized)"]
        L += [f"- {d['summary']} (`{d['slug']}`)" for d in block["decisions"]]
    inds = (seg.get("industries") or ["target industry"])
    geos = (seg.get("geographies") or ["core geo"])
    trig = (seg.get("trigger_signals") or ["a live buying trigger"])
    L += ["", "## 3 example target companies (ILLUSTRATIVE)",
          f"1. A {seg.get('company_size') or 'mid-size'} {inds[0].lower()} player in "
          f"{geos[0]} — why now: {trig[0].lower()}.",
          f"2. A fast-growing {inds[min(1, len(inds)-1)].lower()} operator in "
          f"{geos[-1]} — why now: {trig[min(1, len(trig)-1)].lower()}.",
          f"3. A {inds[-1].lower()} chain expanding its footprint — why now: "
          f"{trig[-1].lower()}.", ""]
    return "\n".join(L)


def cmd_brief(args) -> int:
    with bridge_for_role("gtm", "knowledge") as bridge:
        blocks = gather(bridge, args.segment)
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    for block in blocks:
        try:
            text = brief_via_llm(block) if llm.provider() != "none" \
                else brief_via_template(block)
        except Exception as e:
            print(f"  (LLM unavailable → template mode: {e})")
            text = brief_via_template(block)
        hits = leak_scan(text)
        if hits:
            sys.exit(f"LEAK GUARD TRIPPED — brief mentions {hits}; refusing to write.")
        path = out_dir / (f"brief-{block['segment']['slug']}-"
                          f"{time.strftime('%Y%m%d-%H%M%S')}.md")
        path.write_text(text)
        quotable = sum(1 for p in block["proof"] if p.get("client_safe") is not False)
        internal = len(block["proof"]) - quotable
        print(f"✔ brief written: {path}")
        print(f"  proof kit: {quotable} quotable, {internal} internal-only · leak guard: clean")
    return 0


def cmd_ask(args) -> int:
    with bridge_for_role("gtm", "knowledge") as bridge:
        clean = bridge._clean
        segs = clean(bridge.query(GQ["list_segments"]))
        chunks = clean(bridge.query(GQ["hybrid_chunks"], {"q": args.ask}))
        decisions = clean(bridge.query(GQ["list_decisions"]))
    ctx = ["# SEGMENTS"]
    for s in segs:
        ctx.append(f"- ({s['slug']}) {s['name']}: triggers={s.get('trigger_signals')} "
                   f"pains={s.get('pain_points')}")
    ctx.append("# DECISIONS")
    ctx += [f"- ({d['slug']}) {d['summary']} [{d.get('status')}]" for d in decisions]
    ctx.append("# DOC CHUNKS")
    ctx += [f"- ({c['slug']}) {c['text'][:300]}" for c in chunks[:8]]
    if llm.provider() == "none":
        print(f"Q: {args.ask}\n\nTop graph facts (no LLM configured):\n" + "\n".join(ctx))
        return 0
    answer = llm.complete(
        "Answer from these graph facts only; cite slugs in backticks; "
        "say so if the graph lacks the answer.",
        f"Question: {args.ask}\n\n" + "\n".join(ctx))
    hits = leak_scan(answer)
    if hits:
        sys.exit(f"LEAK GUARD TRIPPED in answer: {hits}")
    print(answer)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Analytos GTM agent (MCP, act-gtm)")
    ap.add_argument("--segment", help="segment slug")
    ap.add_argument("--ask", default=None)
    ap.add_argument("--out", default="out/gtm")
    args = ap.parse_args()
    try:
        return cmd_ask(args) if args.ask else cmd_brief(args)
    except MCPBridgeError as e:
        sys.exit(f"MCP error (Cedar may have denied this actor): {e}")


if __name__ == "__main__":
    sys.exit(main())
