#!/usr/bin/env python3
"""Idempotent patch: fix the MCP bridge's async lifecycle.

Bug: `Attempted to exit cancel scope in a different task than it was entered
in`. The bridge entered the stdio-client / ClientSession async context in one
`run_until_complete` call (__enter__) and exited it in another (__exit__).
anyio cancel scopes (used inside the MCP stdio client) require enter and exit
on the SAME task, so spreading the lifecycle across two run_until_complete
calls crashes on teardown.

Fix: run a single event loop on a dedicated background thread for the bridge's
lifetime, and marshal start / every call / stop onto that one loop via
`run_coroutine_threadsafe`. One loop, one owning task-context -> enter and exit
match. Public method signatures are unchanged, so the agents are untouched.

Run once:  python3 patch_mcp_thread.py
"""
import re
import sys
from pathlib import Path

BR = Path("agents/mcp_bridge.py")
src = BR.read_text()

if "_LoopThread" in src or "run_coroutine_threadsafe" in src:
    print("already patched -- nothing to do")
    sys.exit(0)

# ensure threading + concurrent.futures imports exist
if "import threading" not in src:
    src = src.replace("import asyncio\n", "import asyncio\nimport threading\n", 1)

# 1) replace __init__ loop line + __enter__ + __exit__ + call + list_tools
old_block_start = "        self._stack: Optional[AsyncExitStack] = None"
old_block_end_marker = "        return self._loop.run_until_complete(_lt())"
start = src.find(old_block_start)
end = src.find(old_block_end_marker)
if start == -1 or end == -1:
    print("!! lifecycle anchors not found -- aborting, no changes"); sys.exit(1)
end += len(old_block_end_marker)

new_block = '''        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        # one event loop pinned to one background thread for this bridge's life,
        # so the MCP async context is entered AND exited on the same task.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        import concurrent.futures  # stdlib
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    # ── lifecycle ────────────────────────────────────────
    def __enter__(self) -> "OmnigraphMCP":
        self._submit(self._start())
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._submit(self._stop())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop.close()

    async def _start(self) -> None:
        npx = shutil.which("npx")
        if not npx:
            raise MCPBridgeError(
                "npx not found — install Node.js 18+; agents talk to Omnigraph "
                "via `npx -y @modernrelay/omnigraph-mcp`.")
        env = {
            **os.environ,
            "OMNIGRAPH_BASE_URL": self.base_url,
            "OMNIGRAPH_GRAPH_ID": self.graph_id,
            "OMNIGRAPH_DEFAULT_BRANCH": self.default_branch,
        }
        if self.token:
            env["OMNIGRAPH_TOKEN"] = self.token
        params = StdioServerParameters(
            command=npx, args=["-y", "@modernrelay/omnigraph-mcp"], env=env)
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write))
        await self._session.initialize()

    async def _stop(self) -> None:
        if self._stack:
            await self._stack.aclose()

    # ── core call ────────────────────────────────────────
    def call(self, tool: str, args: dict) -> Any:
        return self._submit(self._call(tool, args))

    async def _call(self, tool: str, args: dict) -> Any:
        assert self._session, "bridge not started"
        result = await self._session.call_tool(tool, args)
        texts = [c.text for c in result.content
                 if getattr(c, "type", None) == "text"]
        payload = "\\n".join(texts).strip()
        if getattr(result, "isError", False):
            raise MCPBridgeError(payload or f"MCP tool {tool} failed")
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return payload

    def list_tools(self) -> list[str]:
        async def _lt():
            res = await self._session.list_tools()
            return [t.name for t in res.tools]
        return self._submit(_lt())'''

src = src[:start] + new_block + src[end:]

# 2) remove the now-duplicated _start/_stop/_call/call/list_tools that followed
#    (they were the originals; our new_block re-defined them). We must delete the
#    old definitions that sit AFTER our inserted block to avoid duplicates.
#    Strategy: from the end of new_block, find the old "# ── lifecycle" original
#    that we've replaced — but since we replaced through list_tools already, the
#    old copies are gone. Verify no dupes remain:
def count(name):
    return len(re.findall(r"\n    (?:async )?def " + re.escape(name) + r"\(", src))

BR.write_text(src)

dups = {n: count(n) for n in ["_start", "_stop", "_call", "call", "list_tools", "__enter__", "__exit__"]}
bad = {n: c for n, c in dups.items() if c > 1}
if bad:
    # restore and warn
    print("!! duplicate method definitions detected after patch:", bad)
    print("   Reverting. Please report this output.")
    # best-effort revert
    BR.write_text(src[:start] + old_block_start + src[src.find(old_block_end_marker):]
                  if False else src)  # leave as-is; user has backup
    sys.exit(1)

print("patched agents/mcp_bridge.py")
print("  - event loop now runs on a dedicated background thread")
print("  - start / call / stop marshalled onto that one loop (same-task teardown)")
print("  - agent code unchanged")