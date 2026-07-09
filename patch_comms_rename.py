#!/usr/bin/env python3
"""Idempotent patch: give the comms graph its OWN node identities.

Root cause of the recurring comms 500 (`.../nodes/85becc3c.../_versions not
found`): both knowledge.pg and comms.pg declared `node Person` and
`node SourceDoc`. Omnigraph derives each table's on-disk path from a hash of
the table identity (type name + shape), so the two graphs computed the SAME
relative dataset path for Person and SourceDoc. Loading knowledge first wrote
those datasets; loading comms second collided with them, tearing comms's
manifest/_versions lineage -> 500 on every comms load, unrepairable by `repair`.

Fix: rename the comms-graph types to CommsPerson / CommsSourceDoc (they are
semantically distinct anyway — external email participants and email files),
so the two graphs never share a table identity. Updates:
  * cluster/comms.pg            (node defs + edges)
  * cluster/queries-comms/*.gq  (match clauses)
  * pipeline/ingest.py          (self.c.node("Person"/"SourceDoc") calls +
                                 the comms hash-lookup type)
  * app/main.py                 (TYPES registry node targets)

After running, RE-APPLY THE CLUSTER (rebuild, since the schema changes):
    Ctrl+C server, rm -rf cluster/graphs, make serve
"""
import re
import sys
from pathlib import Path

changed = []

# ── 1. comms.pg ──────────────────────────────────────────────
pg = Path("cluster/comms.pg")
s = pg.read_text()
if "CommsPerson" in s or "CommsSourceDoc" in s:
    print("comms.pg already patched")
else:
    s = s.replace("node Person {", "node CommsPerson {")
    s = s.replace("node SourceDoc {", "node CommsSourceDoc {")
    # edges reference the node type names on their endpoints
    s = s.replace("edge SentBy: EmailMessage -> Person",
                  "edge SentBy: EmailMessage -> CommsPerson")
    s = s.replace("edge ParticipatesIn: Person -> EmailThread",
                  "edge ParticipatesIn: CommsPerson -> EmailThread")
    pg.write_text(s)
    changed.append("cluster/comms.pg")

# ── 2. comms queries ─────────────────────────────────────────
for q in Path("cluster/queries-comms").glob("*.gq"):
    qs = q.read_text()
    orig = qs
    # `$per: Person`  -> `$per: CommsPerson` ; `$d: SourceDoc` -> CommsSourceDoc
    qs = re.sub(r":\s*Person\b", ": CommsPerson", qs)
    qs = re.sub(r":\s*SourceDoc\b", ": CommsSourceDoc", qs)
    if qs != orig:
        q.write_text(qs)
        changed.append(str(q))

# ── 3. pipeline/ingest.py — only the comms (self.c) uses ──────
ing = Path("pipeline/ingest.py")
i = ing.read_text()
before = i
i = i.replace('target.node("SourceDoc", dict(srcdoc))',
              'target.node("CommsSourceDoc" if x.doc_type == "email_thread" '
              'else "SourceDoc", dict(srcdoc))')
i = i.replace('self.c.node("Person", dict(row))',
              'self.c.node("CommsPerson", dict(row))')
# comms idempotency hash lookup uses a stored query name, not a type — leave it.
if i != before:
    ing.write_text(i)
    changed.append("pipeline/ingest.py")

# ── 4. app/main.py TYPES registry node targets ───────────────
app = Path("app/main.py")
a = app.read_text()
before = a
a = a.replace('"CommsPerson": {"graph": COMMS, "node": "Person",',
              '"CommsPerson": {"graph": COMMS, "node": "CommsPerson",')
a = a.replace('"CommsSourceDoc": {"graph": COMMS, "node": "SourceDoc",',
              '"CommsSourceDoc": {"graph": COMMS, "node": "CommsSourceDoc",')
if a != before:
    app.write_text(a)
    changed.append("app/main.py")

if not changed:
    print("nothing changed (already patched)")
    sys.exit(0)

print("patched:")
for c in changed:
    print("  -", c)
print("\n\u2714 comms graph now uses CommsPerson / CommsSourceDoc — no shared")
print("  table identity with the knowledge graph.")
print("\n  REBUILD REQUIRED (schema changed):")
print("    Ctrl+C server  ->  rm -rf cluster/graphs  ->  make serve")