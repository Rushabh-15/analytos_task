"""Analytos Brain — ingestion pipeline.

seed file(s) ──parse──▶ LLM extract (typed JSON) ──map──▶ NDJSON mutations
       └─ sha256 idempotency check              └─ chunk + embed
                    ──▶ POST /graphs/{g}/load  {branch: ingest/<run>, from: main, mode: merge}

Guarantees
  * NEVER writes to main — every run lands on its own `ingest/<run-id>`
    branch; Cedar denies act-ingest any merge into protected branches.
  * Idempotent — a file whose sha256 already exists as a SourceDoc on main
    is skipped; `--mode merge` upserts by @key; every edge is
    @unique(src, dst), so replays cannot duplicate nodes or edges.
  * Anonymized — extraction prompt strips client names from anything routed
    to the agent-readable knowledge graph; raw thread bodies go only to the
    humans-only comms graph.

Usage:
    python -m pipeline.ingest seed-data/*.md
    python -m pipeline.ingest new-doc.md --run-id demo-day --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .embeddings import Embedder
from .extract import extract, provider_name
from .model import ExtractionResult
from .og_client import OGClient, OGError

KNOWLEDGE = "knowledge"
COMMS = "comms"


# ── helpers ─────────────────────────────────────────────────
def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "x"


def h8(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:8]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunk_text(text: str, target: int = 900) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= target:
            buf = f"{buf}\n\n{p}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = p if len(p) <= target else p[:target]
    if buf:
        chunks.append(buf)
    return chunks


class Rows:
    """NDJSON accumulator with node upsert-by-slug and edge dedupe."""

    def __init__(self) -> None:
        self.nodes: dict[tuple[str, str], dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(self, type_: str, data: dict) -> None:
        key = (type_, data["slug"])
        existing = self.nodes.get(key)
        if existing:
            # richer wins: never let a stub clobber a full extraction
            filled_new = sum(1 for v in data.values() if v not in (None, [], ""))
            filled_old = sum(1 for v in existing["data"].values() if v not in (None, [], ""))
            if filled_new <= filled_old:
                return
        self.nodes[key] = {"type": type_, "data": data}

    def edge(self, edge: str, src: str, dst: str, data: Optional[dict] = None) -> None:
        self.edges[(edge, src, dst)] = {
            "edge": edge, "from": src, "to": dst, "data": data or {}
        }

    def ndjson(self) -> list[str]:
        rows = [json.dumps(r, ensure_ascii=False) for r in self.nodes.values()]
        rows += [json.dumps(r, ensure_ascii=False) for r in self.edges.values()]
        return rows

    def counts(self) -> dict:
        by: dict[str, int] = {}
        for (t, _), _r in self.nodes.items():
            by[t] = by.get(t, 0) + 1
        for (e, _, _), _r in self.edges.items():
            by[f"edge:{e}"] = by.get(f"edge:{e}", 0) + 1
        return by


# ── mapping: ExtractionResult -> graph rows ────────────────
class Mapper:
    def __init__(self, og: OGClient, run_id: str, ts: str, embedder: Embedder):
        self.og = og
        self.run_id = run_id
        self.ts = ts
        self.embedder = embedder
        self.k = Rows()
        self.c = Rows()
        self._main_products: Optional[set[str]] = None

    # provenance boilerplate every knowledge node carries
    def _prov(self, source_doc: str) -> dict:
        return {"source_doc": source_doc, "ingest_run": self.run_id,
                "extracted_at": self.ts, "updated_at": self.ts}

    def _product_exists_on_main(self, slug: str) -> bool:
        if self._main_products is None:
            try:
                res = self.og.query(
                    KNOWLEDGE,
                    "query all_product_slugs() { match { $p: Product } "
                    "return { $p.slug } }",
                    branch="main",
                )
                self._main_products = {
                    r.get("slug") or r.get("$p.slug")
                    for r in _rows_of(res)
                }
            except OGError:
                self._main_products = set()
        return slug in self._main_products

    def _ensure_product(self, name: str, source_doc: str) -> str:
        slug = f"prod-{slugify(name)}"
        if (("Product", slug) not in self.k.nodes
                and not self._product_exists_on_main(slug)):
            self.k.node("Product", {"slug": slug, "name": name,
                                    "tagline": None, "description": None,
                                    "category": None, "stage": None,
                                    "website": None, **self._prov(source_doc)})
        return slug

    def map_doc(self, x: ExtractionResult, filename: str, sha: str,
                content: str) -> None:
        doc_slug = f"doc-{slugify(Path(filename).name)}"
        srcdoc = {"slug": doc_slug, "filename": Path(filename).name,
                  "title": x.title, "doc_type": x.doc_type,
                  "content_sha256": sha, "ingest_run": self.run_id,
                  "ingested_at": self.ts, "updated_at": self.ts}

        target = self.c if x.doc_type == "email_thread" else self.k
        target.node("SourceDoc", dict(srcdoc))

        # knowledge entities can come from ANY doc type (emails yield
        # decisions/proof points); if any do, register provenance there too.
        has_knowledge = any([x.products, x.features, x.proof_points, x.segments,
                             x.personas, x.competitors, x.decisions,
                             any(p.is_internal for p in x.people)])
        if x.doc_type == "email_thread" and has_knowledge:
            self.k.node("SourceDoc", dict(srcdoc))

        # ── knowledge graph ─────────────────────────────
        for p in x.products:
            slug = f"prod-{slugify(p.name)}"
            self.k.node("Product", {"slug": slug, "name": p.name,
                                    "tagline": p.tagline,
                                    "description": p.description,
                                    "category": p.category, "stage": p.stage,
                                    "website": p.website,
                                    **self._prov(doc_slug)})

        for f in x.features:
            pslug = self._ensure_product(f.product, doc_slug)
            fslug = f"feat-{slugify(f.product)}-{slugify(f.name)}"
            self.k.node("Feature", {"slug": fslug, "name": f.name,
                                    "description": f.description,
                                    "differentiator": f.differentiator,
                                    **self._prov(doc_slug)})
            self.k.edge("HasFeature", pslug, fslug)

        for pp in x.proof_points:
            pslug = self._ensure_product(pp.product, doc_slug)
            ppslug = f"proof-{slugify(pp.product)}-{h8(pp.claim)}"
            self.k.node("ProofPoint", {
                "slug": ppslug, "claim": pp.claim,
                "metric_name": pp.metric_name, "metric_value": pp.metric_value,
                "numeric_value": pp.numeric_value, "unit": pp.unit,
                "timeframe": pp.timeframe, "evidence_type": pp.evidence_type,
                "context": pp.context, "client_safe": pp.client_safe,
                **self._prov(doc_slug)})
            self.k.edge("ProvenBy", pslug, ppslug)
            if pp.feature:
                fslug = f"feat-{slugify(pp.product)}-{slugify(pp.feature)}"
                if ("Feature", fslug) in self.k.nodes:
                    self.k.edge("Supports", ppslug, fslug)

        for s in x.segments:
            sslug = f"seg-{slugify(s.name)}"
            self.k.node("ICPSegment", {
                "slug": sslug, "name": s.name, "description": s.description,
                "industries": s.industries or None,
                "company_size": s.company_size,
                "geographies": s.geographies or None,
                "tech_stack_signals": s.tech_stack_signals or None,
                "trigger_signals": s.trigger_signals or None,
                "pain_points": s.pain_points or None,
                "disqualifiers": s.disqualifiers or None,
                **self._prov(doc_slug)})
            for pname in s.target_products:
                pslug = self._ensure_product(pname, doc_slug)
                self.k.edge("Targets", pslug, sslug)

        for per in x.personas:
            perslug = f"persona-{slugify(per.title)}"
            self.k.node("Persona", {
                "slug": perslug, "title": per.title,
                "seniority": per.seniority, "department": per.department,
                "buying_role": per.buying_role,
                "goals": per.goals or None,
                "pain_points": per.pain_points or None,
                "objections": per.objections or None,
                **self._prov(doc_slug)})
            if per.segment:
                self.k.edge("SegmentPersona",
                            f"seg-{slugify(per.segment)}", perslug)

        for comp in x.competitors:
            pslug = self._ensure_product(comp.product, doc_slug)
            cslug = f"comp-{slugify(comp.name)}"
            self.k.node("Competitor", {"slug": cslug, "name": comp.name,
                                       "notes": comp.notes,
                                       "displacement_angle": comp.displacement_angle,
                                       **self._prov(doc_slug)})
            self.k.edge("CompetesWith", pslug, cslug)

        # people: internal -> knowledge (+comms); external -> comms only
        for person in x.people:
            pslug = f"person-{slugify(person.name)}"
            row = {"slug": pslug, "name": person.name, "email": person.email,
                   "org": person.org, "role": person.role,
                   "is_internal": person.is_internal, **self._prov(doc_slug)}
            if person.is_internal:
                self.k.node("Person", dict(row))
            if x.doc_type == "email_thread":
                self.c.node("Person", dict(row))

        for d in x.decisions:
            dslug = f"dec-{h8(d.summary)}"
            self.k.node("Decision", {
                "slug": dslug, "summary": d.summary, "status": d.status,
                "decided_at": d.decided_at, "rationale": d.rationale,
                "thread_ref": (f"thr-{slugify(x.thread.subject)}"
                               if x.thread else None),
                **self._prov(doc_slug)})
            for pname in d.products:
                self.k.edge("About", dslug, self._ensure_product(pname, doc_slug))
            for who in d.decided_by:
                wslug = f"person-{slugify(who)}"
                if ("Person", wslug) in self.k.nodes:
                    self.k.edge("DecidedBy", dslug, wslug)

        # chunks + embeddings for agent-safe docs only (never emails)
        if x.doc_type in ("product_doc", "icp_doc", "other"):
            chunks = chunk_text(content)
            vectors = self.embedder.embed(chunks)
            for i, (text, vec) in enumerate(zip(chunks, vectors)):
                cslug = f"chunk-{doc_slug}-{i:03d}-{h8(text)[:6]}"
                self.k.node("Chunk", {"slug": cslug, "text": text,
                                      "chunk_index": i, "doc_slug": doc_slug,
                                      "embedding": vec,
                                      "extracted_at": self.ts,
                                      "updated_at": self.ts})
                self.k.edge("ChunkOf", cslug, doc_slug)

        # ── comms graph (humans only) ───────────────────
        if x.thread:
            t = x.thread
            tslug = f"thr-{slugify(t.subject)}"
            self.c.node("EmailThread", {
                "slug": tslug, "subject": t.subject, "summary": t.summary,
                "internal_only": t.internal_only,
                "participants": t.participants or None,
                "product_refs": [f"prod-{slugify(n)}" for n in t.product_refs] or None,
                "decision_refs": [f"dec-{h8(d.summary)}" for d in x.decisions] or None,
                "started_at": t.started_at, "source_doc": doc_slug,
                "ingest_run": self.run_id,
                "extracted_at": self.ts, "updated_at": self.ts})
            for m in t.messages:
                mslug = f"{tslug}-m{m.seq:02d}"
                self.c.node("EmailMessage", {
                    "slug": mslug, "thread_slug": tslug, "seq": m.seq,
                    "sender": m.sender, "recipients": m.recipients or None,
                    "sent_at": m.sent_at, "body": m.body,
                    "extracted_at": self.ts, "updated_at": self.ts})
                self.c.edge("InThread", mslug, tslug)
                sender_person = _match_person(m.sender, x)
                if sender_person:
                    self.c.edge("SentBy", mslug,
                                f"person-{slugify(sender_person)}")
            for person in x.people:
                self.c.edge("ParticipatesIn",
                            f"person-{slugify(person.name)}", tslug)


def _match_person(sender: str, x: ExtractionResult) -> Optional[str]:
    s = sender.lower()
    for p in x.people:
        if p.email and p.email.lower() == s:
            return p.name
        if p.name.lower() in s or s in p.name.lower():
            return p.name
    return None


def _rows_of(query_response) -> list[dict]:
    """Normalize a /query response into a list of dict rows."""
    if isinstance(query_response, dict):
        for key in ("rows", "results", "data"):
            if isinstance(query_response.get(key), list):
                return query_response[key]
        return [query_response] if query_response else []
    if isinstance(query_response, list):
        return query_response
    return []


# ── idempotency ─────────────────────────────────────────────
def already_ingested(og: OGClient, sha: str) -> Optional[str]:
    for graph, qname in ((KNOWLEDGE, "sourcedoc_by_hash"),
                         (COMMS, "comms_sourcedoc_by_hash")):
        try:
            res = og.invoke(graph, qname, params={"h": sha}, branch="main")
            rows = _rows_of(res)
            if rows:
                r = rows[0]
                return r.get("filename") or r.get("$d.filename") or "known"
        except OGError as e:
            if e.status in (403, 404):
                continue
            raise
    return None


# ── main ────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Analytos Brain ingestion pipeline")
    ap.add_argument("files", nargs="+", help="documents to ingest (.md/.txt)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--force", action="store_true",
                    help="re-ingest even if the content hash is already on main")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract + map + write NDJSON artifacts, but do not load")
    ap.add_argument("--base-url",
                    default=os.getenv("OMNIGRAPH_BASE_URL", "http://127.0.0.1:8080"))
    args = ap.parse_args(argv)

    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S")
    branch = f"ingest/{run_id}"
    token = os.getenv("OMNIGRAPH_TOKEN_INGEST")
    og = OGClient(args.base_url, token)
    embedder = Embedder()
    ts = now_iso()
    mapper = Mapper(og, run_id, ts, embedder)

    print(f"▶ run {run_id} → branch {branch}")
    print(f"  extractor: {provider_name()}   embedder: {embedder.describe()}")

    out_dir = Path("out") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # process product/icp docs before emails so cross-references resolve rich-first
    def order(p: str) -> int:
        name = Path(p).name.lower()
        return 2 if ("email" in name or "thread" in name) else (
            1 if "icp" in name else 0)

    skipped, processed = [], []
    for path in sorted(args.files, key=order):
        p = Path(path)
        content = p.read_text(encoding="utf-8", errors="replace")
        sha = hashlib.sha256(content.encode()).hexdigest()
        if not args.force and not args.dry_run:
            known = already_ingested(og, sha)
            if known:
                print(f"  ⏭  {p.name}: unchanged (sha256 already on main) — skipped")
                skipped.append(p.name)
                continue
        print(f"  ⛏  extracting {p.name} …")
        result = extract(p.name, content)
        (out_dir / f"extraction-{p.stem}.json").write_text(
            result.model_dump_json(indent=2))
        mapper.map_doc(result, p.name, sha, content)
        processed.append(p.name)

    k_rows, c_rows = mapper.k.ndjson(), mapper.c.ndjson()
    (out_dir / "knowledge.jsonl").write_text("\n".join(k_rows))
    (out_dir / "comms.jsonl").write_text("\n".join(c_rows))
    print(f"  ✎ mapped: knowledge={mapper.k.counts()}")
    print(f"           comms={mapper.c.counts()}")

    if args.dry_run or not processed:
        print("  ✓ dry-run / nothing new — no branch created")
        return 0

    for graph, rows in ((KNOWLEDGE, k_rows), (COMMS, c_rows)):
        if not rows:
            continue
        print(f"  ⇡ loading {len(rows)} rows onto {graph}@{branch} (mode=merge, from=main)")
        res = og.load(graph, rows, branch=branch, from_branch="main", mode="merge")
        print(f"    → {json.dumps(res)[:200]}")

    print(f"\n✔ ingested {len(processed)} doc(s) onto branch '{branch}'."
          f" Skipped {len(skipped)} unchanged.")
    print("  Next: open the Review tab in the dashboard, inspect the diff, and")
    print("  approve (merge) or reject (delete). Agents cannot see this branch;")
    print("  Cedar denies act-ingest any merge into main.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
