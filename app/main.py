"""Analytos Brain — review dashboard backend.

Serves the human-in-the-loop surface:
  * Review queue: every `ingest/*` branch, with a field-level diff vs main.
  * Approve  = merge branch → main on both graphs, using the REVIEWER token,
    so the merge commit is attributed to the human reviewer (act-reviewer).
  * Reject   = delete the branch; nothing ever reaches main.
  * Entity browser, hybrid search (vector+BM25+graph) and activity feed.

The browser never sees Omnigraph tokens: this backend holds the reviewer
token server-side and is itself protected by HTTP Basic auth
(APP_USER / APP_PASSWORD).
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.og_client import OGClient, OGError  # noqa: E402

BASE_URL = os.getenv("OMNIGRAPH_BASE_URL", "http://127.0.0.1:8080")
REVIEWER_TOKEN = os.getenv("OMNIGRAPH_TOKEN_REVIEWER")
KNOWLEDGE, COMMS = "knowledge", "comms"
GRAPHS = (KNOWLEDGE, COMMS)

# fields whose changes are process noise, not content changes
VOLATILE = {"updated_at", "extracted_at", "ingested_at", "ingest_run"}

app = FastAPI(title="Analytos Brain — Review Console")
og = OGClient(BASE_URL, REVIEWER_TOKEN)

security = HTTPBasic(auto_error=False)


def guard(creds: Optional[HTTPBasicCredentials] = Depends(security)):
    user, pw = os.getenv("APP_USER"), os.getenv("APP_PASSWORD")
    if not user or not pw:          # auth disabled for local dev
        return
    ok = (creds is not None
          and secrets.compare_digest(creds.username, user)
          and secrets.compare_digest(creds.password, pw))
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            headers={"WWW-Authenticate": "Basic"})


def _rows(res) -> list[dict]:
    if isinstance(res, dict):
        for key in ("rows", "results", "data"):
            if isinstance(res.get(key), list):
                return res[key]
        return []
    return res if isinstance(res, list) else []


def _oops(e: OGError) -> HTTPException:
    return HTTPException(e.status or 502, detail=str(e))


# ── entity registry (drives browser + ad-hoc reads) ─────────
TYPES: dict[str, dict] = {
    "Product":    {"graph": KNOWLEDGE, "list": ["slug", "name", "tagline", "stage", "category"],
                   "detail": ["slug", "name", "tagline", "description", "category", "stage",
                              "website", "source_doc", "ingest_run", "extracted_at", "updated_at"]},
    "Feature":    {"graph": KNOWLEDGE, "list": ["slug", "name", "differentiator"],
                   "detail": ["slug", "name", "description", "differentiator",
                              "source_doc", "ingest_run", "updated_at"]},
    "ProofPoint": {"graph": KNOWLEDGE, "list": ["slug", "claim", "metric_value", "unit",
                                                "evidence_type", "client_safe"],
                   "detail": ["slug", "claim", "metric_name", "metric_value", "numeric_value",
                              "unit", "timeframe", "evidence_type", "context", "client_safe",
                              "source_doc", "ingest_run", "updated_at"]},
    "ICPSegment": {"graph": KNOWLEDGE, "list": ["slug", "name", "company_size"],
                   "detail": ["slug", "name", "description", "industries", "company_size",
                              "geographies", "tech_stack_signals", "trigger_signals",
                              "pain_points", "disqualifiers", "source_doc", "updated_at"]},
    "Persona":    {"graph": KNOWLEDGE, "list": ["slug", "title", "buying_role", "department"],
                   "detail": ["slug", "title", "seniority", "department", "buying_role",
                              "goals", "pain_points", "objections", "source_doc", "updated_at"]},
    "Competitor": {"graph": KNOWLEDGE, "list": ["slug", "name"],
                   "detail": ["slug", "name", "notes", "displacement_angle",
                              "source_doc", "updated_at"]},
    "Person":     {"graph": KNOWLEDGE, "list": ["slug", "name", "role", "org"],
                   "detail": ["slug", "name", "email", "org", "role", "is_internal",
                              "source_doc", "updated_at"]},
    "Decision":   {"graph": KNOWLEDGE, "list": ["slug", "summary", "status", "decided_at"],
                   "detail": ["slug", "summary", "status", "decided_at", "rationale",
                              "thread_ref", "source_doc", "ingest_run", "updated_at"]},
    "SourceDoc":  {"graph": KNOWLEDGE, "list": ["slug", "filename", "doc_type", "ingested_at"],
                   "detail": ["slug", "filename", "title", "doc_type", "content_sha256",
                              "ingest_run", "ingested_at", "updated_at"]},
    "Chunk":      {"graph": KNOWLEDGE, "list": ["slug", "doc_slug", "chunk_index"],
                   "detail": ["slug", "text", "chunk_index", "doc_slug", "updated_at"]},
    "EmailThread": {"graph": COMMS, "list": ["slug", "subject", "started_at", "internal_only"],
                    "detail": ["slug", "subject", "summary", "internal_only", "participants",
                               "product_refs", "decision_refs", "started_at",
                               "source_doc", "updated_at"]},
    "EmailMessage": {"graph": COMMS, "list": ["slug", "thread_slug", "seq", "sender", "sent_at"],
                     "detail": ["slug", "thread_slug", "seq", "sender", "recipients",
                                "sent_at", "body", "updated_at"]},
    "CommsPerson": {"graph": COMMS, "node": "CommsPerson", "list": ["slug", "name", "org", "role"],
                    "detail": ["slug", "name", "email", "org", "role", "is_internal",
                               "updated_at"]},
    "CommsSourceDoc": {"graph": COMMS, "node": "CommsSourceDoc",
                       "list": ["slug", "filename", "doc_type", "ingested_at"],
                       "detail": ["slug", "filename", "title", "doc_type",
                                  "content_sha256", "ingest_run", "ingested_at"]},
}

# stored queries to hydrate an entity's neighbourhood
NEIGHBORS: dict[str, list[tuple[str, str, str]]] = {
    # type -> [(label, graph, stored_query)]
    "Product": [("features", KNOWLEDGE, "product_features"),
                ("proof_points", KNOWLEDGE, "product_proofpoints"),
                ("segments", KNOWLEDGE, "product_segments"),
                ("competitors", KNOWLEDGE, "product_competitors"),
                ("decisions", KNOWLEDGE, "decisions_about_product")],
    "Feature": [("proof_points", KNOWLEDGE, "feature_proofpoints")],
    "ICPSegment": [("personas", KNOWLEDGE, "segment_personas"),
                   ("products", KNOWLEDGE, "segment_products")],
    "Decision": [("decision_makers", KNOWLEDGE, "decision_makers")],
    "SourceDoc": [("chunks", KNOWLEDGE, "chunks_of_doc")],
    "EmailThread": [("messages", COMMS, "thread_messages"),
                    ("participants", COMMS, "thread_participants")],
}


def _adhoc_list(node: str, fields: list[str]) -> str:
    props = ", ".join(f"$x.{f}" for f in fields)
    return f"query l() {{ match {{ $x: {node} }} return {{ {props} }} limit 500 }}"


def _adhoc_get(node: str, fields: list[str]) -> str:
    props = ", ".join(f"$x.{f}" for f in fields)
    return (f"query g($slug: String) {{ match {{ $x: {node} {{ slug: $slug }} }} "
            f"return {{ {props} }} }}")


def _clean(row: dict) -> dict:
    return { (k.split(".", 1)[1] if "." in k else k): v for k, v in row.items() }


# ── overview & activity ─────────────────────────────────────
@app.get("/api/overview", dependencies=[Depends(guard)])
def overview():
    out = {"graphs": {}, "commits": []}
    for g in GRAPHS:
        try:
            out["graphs"][g] = og.snapshot(g, branch="main")
        except OGError as e:
            out["graphs"][g] = {"error": str(e)}
        try:
            commits = og.commits(g, branch="main")
            items = commits if isinstance(commits, list) else _rows(commits)
            for c in items[:20]:
                c["_graph"] = g
                out["commits"].append(c)
        except OGError:
            pass
    out["commits"] = sorted(
        out["commits"],
        key=lambda c: str(c.get("timestamp") or c.get("created_at") or ""),
        reverse=True)[:30]
    return out


@app.get("/api/commits", dependencies=[Depends(guard)])
def commits(branch: str = "main"):
    out = []
    for g in GRAPHS:
        try:
            items = og.commits(g, branch=branch)
            items = items if isinstance(items, list) else _rows(items)
            for c in items:
                c["_graph"] = g
                out.append(c)
        except OGError:
            pass
    return sorted(out, key=lambda c: str(c.get("timestamp") or ""), reverse=True)


# ── review workflow ─────────────────────────────────────────
@app.get("/api/branches", dependencies=[Depends(guard)])
def branches():
    found: dict[str, dict] = {}
    for g in GRAPHS:
        try:
            for b in og.branches(g):
                name = b if isinstance(b, str) else b.get("name") or b.get("branch")
                if not name or not name.startswith("ingest/"):
                    continue
                found.setdefault(name, {"branch": name, "graphs": []})
                found[name]["graphs"].append(g)
        except OGError as e:
            raise _oops(e)
    return sorted(found.values(), key=lambda x: x["branch"], reverse=True)


def _index_export(rows: list[dict]):
    nodes, edges = {}, {}
    for r in rows:
        if "type" in r:
            data = r.get("data", {})
            nodes[(r["type"], data.get("slug"))] = data
        elif "edge" in r:
            edges[(r["edge"], r.get("from"), r.get("to"))] = r.get("data", {})
    return nodes, edges


def _field_diff(old: dict, new: dict) -> list[dict]:
    out = []
    for k in sorted(set(old) | set(new)):
        if k in VOLATILE:
            continue
        ov, nv = old.get(k), new.get(k)
        if ov == nv:
            continue
        if k == "embedding":
            out.append({"field": "embedding", "old": "(vector)", "new": "(vector changed)"})
            continue
        out.append({"field": k, "old": ov, "new": nv})
    return out


@app.get("/api/diff/{branch:path}", dependencies=[Depends(guard)])
def diff(branch: str):
    result = {"branch": branch, "graphs": {}}
    for g in GRAPHS:
        try:
            names = [b if isinstance(b, str) else b.get("name") or b.get("branch")
                     for b in og.branches(g)]
            if branch not in names:
                continue
            b_nodes, b_edges = _index_export(og.export(g, branch=branch))
            m_nodes, m_edges = _index_export(og.export(g, branch="main"))
        except OGError as e:
            raise _oops(e)

        added, changed = [], []
        for key, data in b_nodes.items():
            t, slug = key
            if key not in m_nodes:
                added.append({"type": t, "slug": slug, "data": _strip_vec(data)})
            else:
                fields = _field_diff(m_nodes[key], data)
                if fields:
                    changed.append({"type": t, "slug": slug, "fields": fields})
        removed = [{"type": t, "slug": s} for (t, s) in m_nodes if (t, s) not in b_nodes]
        e_added = [{"edge": e, "from": f, "to": t}
                   for (e, f, t) in b_edges if (e, f, t) not in m_edges]
        e_removed = [{"edge": e, "from": f, "to": t}
                     for (e, f, t) in m_edges if (e, f, t) not in b_edges]
        result["graphs"][g] = {"added": added, "changed": changed, "removed": removed,
                               "edges_added": e_added, "edges_removed": e_removed,
                               "counts": {"added": len(added), "changed": len(changed),
                                          "removed": len(removed),
                                          "edges_added": len(e_added),
                                          "edges_removed": len(e_removed)}}
    if not result["graphs"]:
        raise HTTPException(404, f"branch '{branch}' not found on any graph")
    return result


def _strip_vec(data: dict) -> dict:
    d = dict(data)
    if isinstance(d.get("embedding"), list):
        d["embedding"] = f"(vector, {len(d['embedding'])} dims)"
    return d


@app.post("/api/branches/{branch:path}/approve", dependencies=[Depends(guard)])
def approve(branch: str):
    if not branch.startswith("ingest/"):
        raise HTTPException(400, "only ingest/* branches are reviewable")
    results = {}
    for g in GRAPHS:
        try:
            names = [b if isinstance(b, str) else b.get("name") or b.get("branch")
                     for b in og.branches(g)]
            if branch not in names:
                continue
            merged = og.branch_merge(g, source=branch, target="main")
            try:
                og.branch_delete(g, branch)
            except OGError:
                pass  # branch cleanup is best-effort
            results[g] = {"merged": True, "result": merged}
        except OGError as e:
            results[g] = {"merged": False, "error": str(e), "status": e.status}
    if not results:
        raise HTTPException(404, f"branch '{branch}' not found on any graph")
    ok = all(r.get("merged") for r in results.values())
    return JSONResponse({"branch": branch, "approved": ok, "by": "act-reviewer",
                         "graphs": results}, status_code=200 if ok else 502)


@app.post("/api/branches/{branch:path}/reject", dependencies=[Depends(guard)])
def reject(branch: str):
    if not branch.startswith("ingest/"):
        raise HTTPException(400, "only ingest/* branches are reviewable")
    results = {}
    for g in GRAPHS:
        try:
            names = [b if isinstance(b, str) else b.get("name") or b.get("branch")
                     for b in og.branches(g)]
            if branch in names:
                og.branch_delete(g, branch)
                results[g] = {"deleted": True}
        except OGError as e:
            results[g] = {"deleted": False, "error": str(e)}
    if not results:
        raise HTTPException(404, f"branch '{branch}' not found on any graph")
    return {"branch": branch, "rejected": True, "graphs": results}


# ── entity browser ──────────────────────────────────────────
@app.get("/api/types", dependencies=[Depends(guard)])
def types():
    return [{"key": k, "graph": v["graph"], "node": v.get("node", k)}
            for k, v in TYPES.items()]


@app.get("/api/entities/{type_key}", dependencies=[Depends(guard)])
def entities(type_key: str, branch: str = "main"):
    spec = TYPES.get(type_key)
    if not spec:
        raise HTTPException(404, f"unknown type {type_key}")
    node = spec.get("node", type_key)
    try:
        res = og.query(spec["graph"], _adhoc_list(node, spec["list"]), branch=branch)
    except OGError as e:
        raise _oops(e)
    return [_clean(r) for r in _rows(res)]


@app.get("/api/entity/{type_key}/{slug}", dependencies=[Depends(guard)])
def entity(type_key: str, slug: str, branch: str = "main"):
    spec = TYPES.get(type_key)
    if not spec:
        raise HTTPException(404, f"unknown type {type_key}")
    node = spec.get("node", type_key)
    try:
        res = og.query(spec["graph"], _adhoc_get(node, spec["detail"]),
                       params={"slug": slug}, branch=branch)
    except OGError as e:
        raise _oops(e)
    rows = _rows(res)
    if not rows:
        raise HTTPException(404, f"{type_key} '{slug}' not found on {branch}")
    out = {"type": type_key, "data": _clean(rows[0]), "neighbors": {}}
    for label, g, qname in NEIGHBORS.get(type_key, []):
        try:
            n = og.invoke(g, qname, params={"slug": slug}, branch=branch)
            out["neighbors"][label] = [_clean(r) for r in _rows(n)]
        except OGError as e:
            out["neighbors"][label] = {"error": str(e)}
    return out


# ── search (hybrid: vector + BM25 via RRF, plus entity FTS) ─
@app.get("/api/search", dependencies=[Depends(guard)])
def search(q: str = Query(..., min_length=1), branch: str = "main"):
    out = {"query": q, "chunks": [], "products": [], "proof_points": [],
           "segments": []}
    calls = [("chunks", "hybrid_chunks"), ("products", "search_products"),
             ("proof_points", "search_proofpoints"), ("segments", "search_segments")]
    for key, qname in calls:
        try:
            res = og.invoke(KNOWLEDGE, qname, params={"q": q}, branch=branch)
            out[key] = [_clean(r) for r in _rows(res)]
        except OGError as e:
            out[key] = [{"error": str(e)}]
    return out


# ── comms views (humans only — this backend uses the reviewer token) ─
@app.get("/api/thread/{slug}", dependencies=[Depends(guard)])
def thread(slug: str, branch: str = "main"):
    try:
        head = _rows(og.invoke(COMMS, "get_thread", params={"slug": slug}, branch=branch))
        msgs = _rows(og.invoke(COMMS, "thread_messages", params={"slug": slug}, branch=branch))
        ppl = _rows(og.invoke(COMMS, "thread_participants", params={"slug": slug}, branch=branch))
    except OGError as e:
        raise _oops(e)
    if not head:
        raise HTTPException(404, f"thread '{slug}' not found")
    return {"thread": _clean(head[0]),
            "messages": sorted((_clean(m) for m in msgs), key=lambda m: m.get("seq", 0)),
            "participants": [_clean(p) for p in ppl]}


@app.get("/healthz")
def healthz():
    # Unauthenticated liveness probe for Render's health check.
    # Always 200 when the web app is up; no Basic auth, no Omnigraph dependency,
    # so a slow or cold graph never fails the deploy.
    return {"status": "ok"}

@app.get("/api/health", dependencies=[Depends(guard)])
def health():
    try:
        return {"app": "ok", "omnigraph": og.healthz(), "base_url": BASE_URL,
                "reviewer_token_set": bool(REVIEWER_TOKEN)}
    except OGError as e:
        return JSONResponse({"app": "ok", "omnigraph": f"unreachable: {e}"},
                            status_code=502)


# ── static UI ───────────────────────────────────────────────
STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", dependencies=[Depends(guard)])
def index():
    return FileResponse(str(STATIC / "index.html"))
