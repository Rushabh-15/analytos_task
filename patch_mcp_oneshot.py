#!/usr/bin/env python3
"""Idempotent patch: make the MCP bridge per-call atomic.

The background-thread approach still tripped anyio's cancel-scope check because
each _submit() ran a NEW coroutine (a new task): the session was entered in one
task and exited in another. anyio requires enter+exit in the SAME task.

Definitive fix: every tool call is one self-contained `asyncio.run(_one_shot())`
that spawns the MCP server, initializes, runs the single tool call, and tears
down — all inside ONE coroutine, so the stdio_client / ClientSession cancel
scopes always enter and exit in the same task. A bit more overhead (one npx
process per query) but for ~10 queries/agent it's negligible and, crucially,
correct. Public methods are unchanged, so the agents and negative_demo are
untouched.

Run once:  python3 patch_mcp_oneshot.py
"""
import re
import sys
from pathlib import Path

BR = Path("agents/mcp_bridge.py")
src = BR.read_text()

if "def _one_shot(" in src:
    print("already patched -- nothing to do")
    sys.exit(0)

# Find the class body from `class OmnigraphMCP` up to the line before the
# `# canned GQ` block (the module-level GQ dict), and replace it wholesale.
cls_start = src.find("class OmnigraphMCP:")
gq_marker = src.find("# canned GQ")
if cls_start == -1 or gq_marker == -1:
    print("!! could not locate class / GQ boundary -- aborting"); sys.exit(1)

new_class = '''class OmnigraphMCP:
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
                payload = "\\n".join(texts).strip()
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


'''

src = src[:cls_start] + new_class + src[gq_marker:]

# AsyncExitStack / threading no longer needed; leave imports (harmless) but
# drop the now-unused threading import to keep it clean if present.
src = src.replace("import threading\n", "")

BR.write_text(src)

# sanity: no duplicate method defs, still imports
import ast
try:
    ast.parse(src)
except SyntaxError as e:
    print("!! patched file has a syntax error, reverting not automatic:", e)
    sys.exit(1)

print("patched agents/mcp_bridge.py")
print("  - OmnigraphMCP is now per-call atomic (asyncio.run per tool call)")
print("  - cancel scopes always enter+exit in the same task")
print("  - agent code unchanged")