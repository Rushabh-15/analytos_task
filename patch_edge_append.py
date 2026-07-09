#!/usr/bin/env python3
"""Idempotent patch: load nodes and edges with the correct modes.

Root cause (confirmed against Omnigraph docs):
  * `load --mode merge` upserts by @key. NODES have @key -> merge is idempotent.
  * EDGES have NO @key, so merge cannot upsert them; every edge is an INSERT and
    the @unique(src,dst) constraint rejects any tuple that already exists (even
    the engine's own mid-batch re-write). The documented mode for known-new rows
    is `append`.

Fix: og.load() now splits the payload — nodes via `merge`, edges via `append`,
both onto the same branch (branch forked from `from_branch` on the first call).
Combined with the delta filter (which guarantees edges are new vs the base
branch) this makes ingest fully re-runnable, and the subsequent branch->main
merge is a clean fast-forward.

Run once:  python3 patch_edge_append.py
"""
import sys
from pathlib import Path

OGC = Path("pipeline/og_client.py")
src = OGC.read_text()

if "def load_split(" in src or "nodes via merge, edges via append" in src:
    print("already patched -- nothing to do")
    sys.exit(0)

old_load = '''    def load(self, graph: str, ndjson_lines: Iterable[str], *,
             branch: str, from_branch: Optional[str] = None,
             mode: str = "merge") -> Any:
        body: dict = {"data": "\\n".join(ndjson_lines), "branch": branch, "mode": mode}
        if from_branch:
            body["from"] = from_branch
        return self._req("POST", f"/graphs/{graph}/load", json_body=body).json()'''

new_load = '''    def _load_raw(self, graph: str, ndjson_lines: Iterable[str], *,
                  branch: str, from_branch: Optional[str] = None,
                  mode: str = "merge") -> Any:
        body: dict = {"data": "\\n".join(ndjson_lines), "branch": branch, "mode": mode}
        if from_branch:
            body["from"] = from_branch
        return self._req("POST", f"/graphs/{graph}/load", json_body=body).json()

    def load(self, graph: str, ndjson_lines: Iterable[str], *,
             branch: str, from_branch: Optional[str] = None,
             mode: str = "merge") -> Any:
        """Split load: nodes via merge, edges via append.
        Nodes have @key so `merge` upserts them idempotently. Edges have no
        @key, so `merge` would try to INSERT each one and the @unique(src,dst)
        constraint rejects any existing tuple; `append` is the correct mode for
        known-new rows (the pipeline's delta filter guarantees novelty).
        The branch is forked from `from_branch` on the FIRST call that touches
        it; subsequent calls append onto the now-existing branch.
        """
        lines = [l for l in ndjson_lines if l.strip()]
        nodes, edges = [], []
        for l in lines:
            (edges if '"edge"' in l and _is_edge(l) else nodes).append(l)

        results = {}
        first_from = from_branch
        if nodes:
            results["nodes"] = self._load_raw(
                graph, nodes, branch=branch, from_branch=first_from, mode="merge")
            first_from = None  # branch now exists; don't re-fork
        if edges:
            # if there were no nodes, the branch still needs creating on this call
            results["edges"] = self._load_raw(
                graph, edges, branch=branch,
                from_branch=(first_from if not nodes else None), mode="append")
        return results or {"loaded": 0}'''

if old_load not in src:
    print("!! load() anchor not found -- aborting, no changes"); sys.exit(1)
src = src.replace(old_load, new_load, 1)

# helper to robustly classify a JSONL line as an edge row.
# Anchor BEFORE the @dataclass decorator so we never split it from its class.
if "def _is_edge(" not in src:
    helper = (
        'def _is_edge(line: str) -> bool:\n'
        '    """True if this NDJSON line is an edge row ({\\"edge\\":...}) rather\n'
        '    than a node row ({\\"type\\":...})."""\n'
        '    import json as _json\n'
        '    try:\n'
        '        return "edge" in _json.loads(line)\n'
        '    except Exception:\n'
        '        return False\n\n\n'
    )
    for anchor in ("@dataclass\nclass OGClient", "class OGClient"):
        if anchor in src:
            src = src.replace(anchor, helper + anchor, 1)
            break
    else:
        print("!! OGClient class anchor not found -- aborting"); sys.exit(1)

OGC.write_text(src)
print("patched pipeline/og_client.py")
print("  - og.load() now splits: nodes=merge, edges=append (same branch)")
print("  - added _is_edge() classifier")