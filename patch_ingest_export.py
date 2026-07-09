#!/usr/bin/env python3
"""Idempotent patch: let the ingest role read main for its idempotency diff.

Root cause: the pipeline computes its load-delta by exporting `main` and
filtering out rows that already exist. But `export` is a distinct Cedar action
and `act-ingest` only had `read` — so the export was denied (403), the pipeline
saw an empty main, filtered nothing, and re-inserting an existing edge tripped
the @unique(src,dst) constraint (HTTP 400).

Fix: grant `ingestors` the `export` action, scoped to PROTECTED branches only
(i.e. main). This is exactly and only what an idempotent ingest needs — diff
against the published graph — and it does NOT let ingest export unreviewed
branches, nor merge, nor write to main. Least privilege is preserved.

Edits both cluster/policies/knowledge.policy.yaml and comms.policy.yaml.
After running, re-apply the cluster (make serve re-runs apply on boot).

Run once:  python3 patch_ingest_export.py
"""
import sys
from pathlib import Path

GRANT = '''  - id: ingest-export-main-for-diff
    allow:
      actors: { group: ingestors }
      actions: [export]
      branch_scope: protected
'''

ANCHOR = '''  - id: ingest-read-for-idempotency
    allow:
      actors: { group: ingestors }
      actions: [read]
      branch_scope: any
'''

changed = []
for name in ("knowledge.policy.yaml", "comms.policy.yaml"):
    p = Path("cluster/policies") / name
    if not p.exists():
        print(f"  (skip {name}: not found)")
        continue
    src = p.read_text()
    if "ingest-export-main-for-diff" in src:
        print(f"  {name}: already patched")
        continue
    if ANCHOR not in src:
        print(f"  !! {name}: idempotency-rule anchor not found — aborting this file")
        continue
    src = src.replace(ANCHOR, ANCHOR + "\n" + GRANT, 1)
    p.write_text(src)
    changed.append(name)
    print(f"  patched {name}")

if changed:
    print("\n✔ added scoped export grant for act-ingest (protected/main only)")
    print("  RE-APPLY THE CLUSTER for this to take effect:")
    print("    stop make serve (Ctrl+C), then `make serve` again")
else:
    print("\nno changes")