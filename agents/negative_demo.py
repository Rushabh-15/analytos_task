"""Negative demo — proves Cedar blocks the content agent from EmailThreads.

The content agent's token (act-content) appears in NO rule of
cluster/policies/comms.policy.yaml, and Omnigraph policies are default-deny.
So when the very same MCP server that works against `knowledge` is pointed
at `comms`, every tool call is rejected by the engine (HTTP 403), before any
data leaves the store. This is enforcement at the engine, not agent
politeness.

Run:  python -m agents.negative_demo
Exit code 0 only if BOTH checks hold:
  1. act-content CAN read products from `knowledge`.
  2. act-content CANNOT read threads from `comms` (denied by Cedar).
"""
from __future__ import annotations

import sys

from .mcp_bridge import GQ, MCPBridgeError, bridge_for_role

THREADS_GQ = ("query l() { match { $t: EmailThread } "
              "return { $t.slug, $t.subject } limit 5 }")


def main() -> int:
    print("── 1/2 · act-content → knowledge (should SUCCEED)")
    try:
        with bridge_for_role("content", "knowledge") as b:
            rows = b.query(GQ["list_products"])
        print(f"   ✔ allowed — read {len(rows)} products from knowledge@main")
    except MCPBridgeError as e:
        print(f"   ✘ unexpected denial: {e}")
        return 1

    print("── 2/2 · act-content → comms EmailThread (should be DENIED)")
    try:
        with bridge_for_role("content", "comms") as b:
            rows = b.query(THREADS_GQ)
    except MCPBridgeError as e:
        msg = str(e)
        if "403" in msg or "denied" in msg.lower() or "forbidden" in msg.lower():
            print(f"   ✔ denied by the engine, as designed → {msg[:160]}")
            print("\nPASS — content agent can use product knowledge but the "
                  "engine (Cedar, default-deny) blocks every read of the "
                  "comms graph. No client email is reachable by this actor.")
            return 0
        print(f"   ✘ failed, but not with an authorization error: {msg[:200]}")
        return 1
    print(f"   ✘ SECURITY GAP — read {len(rows)} threads; policy misconfigured")
    return 1


if __name__ == "__main__":
    sys.exit(main())
