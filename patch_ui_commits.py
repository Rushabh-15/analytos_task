#!/usr/bin/env python3
"""Idempotent patch: fix the review console's commit rendering.
  * created_at from the engine is in MICROSECONDS -> convert to ms for Date().
  * commit fields are graph_commit_id / actor_id / created_at (not actor/author).
Run once:  python3 patch_ui_commits.py"""
import sys
from pathlib import Path

UI = Path("app/static/index.html")
src = UI.read_text()

if "tsMicros" in src:
    print("already patched -- nothing to do")
    sys.exit(0)

old_ts = ('function ts(v){if(!v)return"";const d=new Date(v);'
          'return isNaN(d)?esc(v):d.toISOString().replace("T"," ").slice(0,16)+"Z";}')
new_ts = (
    'function ts(v){if(v===null||v===undefined||v==="")return"";'
    'let n=Number(v);'
    'if(Number.isFinite(n)){if(n>1e15){n=Math.floor(n/1000);}'
    'else if(n<1e11){n=n*1000;}}'
    'const d=new Date(Number.isFinite(n)?n:v);'
    'return isNaN(d)?esc(v):d.toISOString().replace("T"," ").slice(0,16)+"Z";}'
    '\nfunction tsMicros(){/* marker: ui commit patch applied */}'
)
if old_ts not in src:
    print("!! ts() anchor not found -- aborting"); sys.exit(1)
src = src.replace(old_ts, new_ts, 1)

src = src.replace(
    'const actor=c.actor||c.author||c.as||"?";',
    'const actor=c.actor_id||c.actor||c.author||c.as||"(system)";', 1)

src = src.replace(
    'const msg=c.message||c.summary||c.op||"";',
    'const msg=c.message||c.summary||c.op||(c.merged_parent_commit_id?"merge":(c.parent_commit_id?"commit":"init"));', 1)

src = src.replace(
    'const id=(c.id||c.commit||c.hash||"").toString().slice(0,10);',
    'const id=(c.graph_commit_id||c.id||c.commit||c.hash||"").toString().slice(0,10);', 1)

src = src.replace(
    '<td class="mono">${ts(c.timestamp||c.created_at||c.time)}</td></tr>`;}).join("");',
    '<td class="mono">${ts(c.created_at||c.timestamp||c.time)}</td></tr>`;}).join("");', 1)

UI.write_text(src)
print("patched app/static/index.html")
print("  - ts() now handles microsecond epochs")
print("  - commit rows read graph_commit_id / actor_id / created_at")
