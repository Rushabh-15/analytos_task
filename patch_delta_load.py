#!/usr/bin/env python3
"""Idempotent patch: make the ingest pipeline load only the DELTA vs the base
branch, so re-ingesting overlapping content never hits @unique edge
violations or divergent-insert merge conflicts.

Run once:  python3 patch_delta_load.py
Safe to run twice (checks whether it's already applied)."""
import re
import sys
from pathlib import Path

ING = Path("pipeline/ingest.py")
src = ING.read_text()

if "def delta_against(" in src:
    print("already patched — nothing to do")
    sys.exit(0)

# 1) add delta_against() to the Rows class, right after ndjson()
ndjson_method = '''    def ndjson(self) -> list[str]:
        rows = [json.dumps(r, ensure_ascii=False) for r in self.nodes.values()]
        rows += [json.dumps(r, ensure_ascii=False) for r in self.edges.values()]
        return rows
'''

delta_method = '''    def ndjson(self) -> list[str]:
        rows = [json.dumps(r, ensure_ascii=False) for r in self.nodes.values()]
        rows += [json.dumps(r, ensure_ascii=False) for r in self.edges.values()]
        return rows

    def delta_against(self, existing_rows: list[dict]) -> "Rows":
        """Return a NEW Rows holding only what differs from `existing_rows`
        (an export of the base branch). Edges already present are dropped
        entirely (any re-insert of a @unique(src,dst) tuple is a hard error,
        not a no-op). Nodes are dropped only when byte-identical on the
        content fields; changed nodes are kept so merge upserts them."""
        VOLATILE = {"updated_at", "extracted_at", "ingested_at", "ingest_run"}
        have_nodes: dict[tuple, dict] = {}
        have_edges: set[tuple] = set()
        for r in existing_rows:
            if "type" in r:
                d = r.get("data", {})
                have_nodes[(r["type"], d.get("slug"))] = d
            elif "edge" in r:
                have_edges.add((r["edge"], r.get("from"), r.get("to")))

        def content(d: dict) -> dict:
            return {k: v for k, v in d.items() if k not in VOLATILE}

        out = Rows()
        for key, row in self.nodes.items():
            old = have_nodes.get(key)
            if old is not None and content(old) == content(row["data"]):
                continue  # unchanged — skip
            out.nodes[key] = row
        for key, row in self.edges.items():
            if key in have_edges:
                continue  # already on base branch — never re-insert
            out.edges[key] = row
        return out
'''

if ndjson_method not in src:
    print("!! could not find ndjson() anchor — aborting, no changes written")
    sys.exit(1)
src = src.replace(ndjson_method, delta_method, 1)

# 2) rewrite the load loop to diff against the base branch first
old_loop = '''    for graph, rows in ((KNOWLEDGE, k_rows), (COMMS, c_rows)):
        if not rows:
            continue
        print(f"  \u21e1 loading {len(rows)} rows onto {graph}@{branch} (mode=merge, from=main)")
        res = og.load(graph, rows, branch=branch, from_branch="main", mode="merge")
        print(f"    \u2192 {json.dumps(res)[:200]}")'''

new_loop = '''    for graph, accum in ((KNOWLEDGE, mapper.k), (COMMS, mapper.c)):
        full = accum.ndjson()
        if not full:
            continue
        # delta vs base branch: drop pre-existing edges (unique) + identical nodes
        try:
            base = og.export(graph, branch="main")
        except OGError:
            base = []
        delta = accum.delta_against(base)
        rows = delta.ndjson()
        if not rows:
            print(f"  \u2713 {graph}: nothing new vs main (all {len(full)} rows already present) — skipping load")
            continue
        print(f"  \u21e1 loading {len(rows)} new/changed rows onto {graph}@{branch} "
              f"(of {len(full)} mapped; mode=merge, from=main)")
        res = og.load(graph, rows, branch=branch, from_branch="main", mode="merge")
        print(f"    \u2192 {json.dumps(res)[:200]}")'''

if old_loop not in src:
    print("!! could not find the load loop anchor — aborting, no changes written")
    sys.exit(1)
src = src.replace(old_loop, new_loop, 1)

# 3) ensure OGError is imported (used in the new try/except)
if "OGError" not in src.split("\n\n")[0] and "import OGError" not in src:
    src = re.sub(r"(from \.og_client import [^\n]*OGClient)",
                 lambda m: m.group(1) if "OGError" in m.group(1)
                 else m.group(1).replace("OGClient", "OGClient, OGError"),
                 src, count=1)

ING.write_text(src)
print("✔ patched pipeline/ingest.py")
print("  - Rows.delta_against() added")
print("  - load loop now diffs against main and loads only new/changed rows")
