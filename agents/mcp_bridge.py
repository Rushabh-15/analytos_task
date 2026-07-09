"""MCP bridge — agents reach Omnigraph ONLY through @modernrelay/omnigraph-mcp.

Each agent role gets its own MCP server process, pinned to one graph and one
bearer token, exactly like a Claude Desktop connector would be configured:

    npx -y @modernrelay/omnigraph-mcp
      OMNIGRAPH_BASE_URL      http://127.0.0.1:8080
      OMNIGRAPH_GRAPH_ID      knowledge          (one graph per instance)
      OMNIGRAPH_TOKEN         <role token>       (act-content / act-gtm)
      OMNIGRAPH_DEFAULT_BRANCH main

Every read below goes through the MCP `query` tool, so Cedar evaluates the
actor on each call. Pointing the same bridge at the `comms` graph with the
content-agent token yields an engine-level 403 — that is the negative test
in agents/negative_demo.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPBridgeError(RuntimeError):
    pass


class OmnigraphMCP:
    """Per-call-atomic wrapper around @modernrelay/omnigraph-mcp.

    Each tool call opens a fresh MCP stdio session, runs one call, and closes
    it — entirely within a single coroutine driven by asyncio.run(). This keeps
    anyio's cancel scopes intact (enter+exit on the same task) and needs no
    background threads or persistent session juggling.
    """

    def __init__(self, graph_id: str, token: Optional[str],
                 base_url: Optional[str] = None, default_branch: str = "main"):
        self.graph_id = graph_id
        self.token = token
        self.base_url = base_url or os.getenv("OMNIGRAPH_BASE_URL",
                                              "http://127.0.0.1:8080")
        self.default_branch = default_branch

    # context-manager surface kept so agents can still use `with ...:`
    def __enter__(self) -> "OmnigraphMCP":
        # fail fast if npx is missing, with a clear message
        if not shutil.which("npx"):
            raise MCPBridgeError(
                "npx not found — install Node.js 18+; agents talk to Omnigraph "
                "via `npx -y @modernrelay/omnigraph-mcp`.")
        return self

    def __exit__(self, *exc) -> None:
        return None

    def _server_params(self) -> StdioServerParameters:
        npx = shutil.which("npx")
        if not npx:
            raise MCPBridgeError(
                "npx not found — install Node.js 18+ to run the MCP server.")
        env = {
            **os.environ,
            "OMNIGRAPH_BASE_URL": self.base_url,
            "OMNIGRAPH_GRAPH_ID": self.graph_id,
            "OMNIGRAPH_DEFAULT_BRANCH": self.default_branch,
        }
        if self.token:
            env["OMNIGRAPH_TOKEN"] = self.token
        return StdioServerParameters(
            command=npx, args=["-y", "@modernrelay/omnigraph-mcp"], env=env)

    async def _one_shot(self, tool: str, args: dict) -> Any:
        """Open session -> initialize -> call one tool -> close, all in one task."""
        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                texts = [c.text for c in result.content
                         if getattr(c, "type", None) == "text"]
                payload = "\n".join(texts).strip()
                if getattr(result, "isError", False):
                    raise MCPBridgeError(payload or f"MCP tool {tool} failed")
                try:
                    return json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    return payload

    async def _one_shot_list(self) -> list[str]:
        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
                return [t.name for t in res.tools]

    # ── public API (unchanged signatures) ────────────────
    def call(self, tool: str, args: dict) -> Any:
        return asyncio.run(self._one_shot(tool, args))

    def list_tools(self) -> list[str]:
        return asyncio.run(self._one_shot_list())

    def query(self, gq: str, params: Optional[dict] = None,
              branch: Optional[str] = None) -> list[dict]:
        args: dict[str, Any] = {"query": gq}
        if params:
            args["params"] = params
        if branch:
            args["branch"] = branch
        res = self.call("query", args)
        if isinstance(res, dict):
            for key in ("rows", "results", "data"):
                if isinstance(res.get(key), list):
                    return res[key]
            return []
        return res if isinstance(res, list) else []

    @staticmethod
    def _clean(rows: list[dict]) -> list[dict]:
        return [{(k.split(".", 1)[1] if "." in k else k): v
                 for k, v in r.items()} for r in rows]


# canned GQ, kept byte-compatible with cluster/queries/*.gq
GQ = {
    "list_products": "query l() { match { $p: Product } "
        "return { $p.slug, $p.name, $p.tagline, $p.stage, $p.category } "
        "order { $p.name } }",
    "get_product": "query g($slug: String) { match { $p: Product { slug: $slug } } "
        "return { $p.slug, $p.name, $p.tagline, $p.description, $p.category, "
        "$p.stage, $p.website, $p.source_doc } }",
    "product_features": "query q($slug: String) { match { "
        "$p: Product { slug: $slug } $p hasFeature $f } "
        "return { $f.slug, $f.name, $f.description, $f.differentiator } }",
    "product_proofpoints": "query q($slug: String) { match { "
        "$p: Product { slug: $slug } $p provenBy $pp } "
        "return { $pp.slug, $pp.claim, $pp.metric_name, $pp.metric_value, "
        "$pp.numeric_value, $pp.unit, $pp.timeframe, $pp.evidence_type, "
        "$pp.context, $pp.client_safe, $pp.source_doc } }",
    "product_segments": "query q($slug: String) { match { "
        "$p: Product { slug: $slug } $p targets $s } "
        "return { $s.slug, $s.name, $s.description, $s.industries, "
        "$s.company_size } }",
    "product_competitors": "query q($slug: String) { match { "
        "$p: Product { slug: $slug } $p competesWith $c } "
        "return { $c.slug, $c.name, $c.notes, $c.displacement_angle } }",
    "list_segments": "query l() { match { $s: ICPSegment } "
        "return { $s.slug, $s.name, $s.description, $s.industries, "
        "$s.company_size, $s.geographies, $s.tech_stack_signals, "
        "$s.trigger_signals, $s.pain_points, $s.disqualifiers } "
        "order { $s.name } }",
    "segment_personas": "query q($slug: String) { match { "
        "$s: ICPSegment { slug: $slug } $s segmentPersona $per } "
        "return { $per.slug, $per.title, $per.seniority, $per.department, "
        "$per.buying_role, $per.goals, $per.pain_points, $per.objections } }",
    "segment_products": "query q($slug: String) { match { "
        "$s: ICPSegment { slug: $slug } $p: Product $p targets $s } "
        "return { $p.slug, $p.name, $p.tagline } }",
    "list_decisions": "query l() { match { $d: Decision } "
        "return { $d.slug, $d.summary, $d.status, $d.decided_at, $d.rationale } "
        "order { $d.decided_at desc } }",
    "decisions_about_product": "query q($slug: String) { match { "
        "$p: Product { slug: $slug } $d: Decision $d about $p } "
        "return { $d.slug, $d.summary, $d.status, $d.decided_at, $d.rationale } }",
    "hybrid_chunks": "query q($q: String) { match { $c: Chunk } "
        "return { $c.slug, $c.text, $c.doc_slug, $c.chunk_index } "
        "order { rrf(nearest($c.embedding, $q), bm25($c.text, $q)) } limit 12 }",
    "search_proofpoints": "query q($q: String) { match { $pp: ProofPoint "
        "search($pp.claim, $q) } return { $pp.slug, $pp.claim, "
        "$pp.metric_value, $pp.unit, $pp.client_safe } }",
}


def bridge_for_role(role: str, graph_id: str = "knowledge") -> OmnigraphMCP:
    token_env = {"content": "OMNIGRAPH_TOKEN_CONTENT",
                 "gtm": "OMNIGRAPH_TOKEN_GTM",
                 "reviewer": "OMNIGRAPH_TOKEN_REVIEWER",
                 "ingest": "OMNIGRAPH_TOKEN_INGEST"}[role]
    return OmnigraphMCP(graph_id=graph_id, token=os.getenv(token_env))
