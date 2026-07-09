"""Thin HTTP client for omnigraph-server (cluster mode, /graphs/{id}/...).

Every call is bearer-authenticated; the SERVER resolves the actor from the
token (clients cannot forge identity), so attribution in commits/audit is
trustworthy by construction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import requests


class OGError(RuntimeError):
    def __init__(self, status: int, message: str, url: str):
        super().__init__(f"HTTP {status} from {url}: {message}")
        self.status = status
        self.body = message
        self.url = url


def _is_edge(line: str) -> bool:
    """True if this NDJSON line is an edge row ({\"edge\":...}) rather
    than a node row ({\"type\":...})."""
    import json as _json
    try:
        return "edge" in _json.loads(line)
    except Exception:
        return False


@dataclass
class OGClient:
    base_url: str
    token: Optional[str] = None
    timeout: int = 120

    # ── internals ────────────────────────────────────────────
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, *, json_body: Any = None,
             params: Optional[dict] = None, stream: bool = False) -> requests.Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        r = requests.request(method, url, headers=self._headers(),
                             json=json_body, params=params,
                             timeout=self.timeout, stream=stream)
        if r.status_code >= 400:
            raise OGError(r.status_code, r.text[:2000], url)
        return r

    # ── health / topology ───────────────────────────────────
    def healthz(self) -> bool:
        return self._req("GET", "/healthz").ok

    def graphs(self) -> Any:
        return self._req("GET", "/graphs").json()

    # ── reads ────────────────────────────────────────────────
    def query(self, graph: str, gq: str, *, name: Optional[str] = None,
              params: Optional[dict] = None, branch: Optional[str] = None) -> Any:
        body: dict = {"query": gq}
        if name:
            body["name"] = name
        if params:
            body["params"] = params
        if branch:
            body["branch"] = branch
        return self._req("POST", f"/graphs/{graph}/query", json_body=body).json()

    def invoke(self, graph: str, stored_name: str, *,
               params: Optional[dict] = None, branch: Optional[str] = None) -> Any:
        qp = {"branch": branch} if branch else None
        body = {"params": params or {}}
        return self._req("POST", f"/graphs/{graph}/queries/{stored_name}",
                         json_body=body, params=qp).json()

    def stored_queries(self, graph: str) -> Any:
        return self._req("GET", f"/graphs/{graph}/queries").json()

    def snapshot(self, graph: str, branch: str = "main") -> Any:
        return self._req("GET", f"/graphs/{graph}/snapshot",
                         params={"branch": branch}).json()

    def schema(self, graph: str) -> str:
        return self._req("GET", f"/graphs/{graph}/schema").text

    def export(self, graph: str, branch: str = "main",
               type_names: Optional[list[str]] = None) -> list[dict]:
        """Buffered + retry export. Reads the whole NDJSON body (no streaming)
        and retries transient premature-stream / chunk-decode drops, which the
        Omnigraph docs flag as expected 504-class flakiness."""
        import time as _time
        body: dict = {"branch": branch}
        if type_names:
            body["type_names"] = type_names
        url = f"{self.base_url.rstrip('/')}/graphs/{graph}/export"
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = requests.request("POST", url, headers=self._headers(),
                                     json=body, timeout=self.timeout, stream=False)
                if r.status_code >= 400:
                    raise OGError(r.status_code, r.text[:2000], url)
                text = r.text
                rows: list[dict] = []
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
                return rows
            except OGError:
                raise  # a real 4xx/5xx status is not a transient read drop
            except Exception as e:  # ChunkedEncodingError, ProtocolError, ConnErr
                last_err = e
                _time.sleep(0.6 * (attempt + 1))
        raise OGError(0, f"export failed after retries: {last_err}", url)

    # ── writes (Cedar-gated server-side) ────────────────────
    def _load_raw(self, graph: str, ndjson_lines: Iterable[str], *,
                  branch: str, from_branch: Optional[str] = None,
                  mode: str = "merge") -> Any:
        body: dict = {"data": "\n".join(ndjson_lines), "branch": branch, "mode": mode}
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
        return results or {"loaded": 0}

    def mutate(self, graph: str, gq: str, *, name: Optional[str] = None,
               params: Optional[dict] = None, branch: Optional[str] = None) -> Any:
        body: dict = {"query": gq}
        if name:
            body["name"] = name
        if params:
            body["params"] = params
        if branch:
            body["branch"] = branch
        return self._req("POST", f"/graphs/{graph}/mutate", json_body=body).json()

    # ── branches / history ──────────────────────────────────
    def branches(self, graph: str) -> list[str]:
        raw = self._req("GET", f"/graphs/{graph}/branches").json()
        # server returns {"branches": [...]}; tolerate a bare list or dicts too
        items = raw.get("branches", raw) if isinstance(raw, dict) else raw
        out = []
        for b in (items or []):
            name = b if isinstance(b, str) else (b.get("name") or b.get("branch"))
            if name:
                out.append(name)
        return out

    def branch_create(self, graph: str, name: str, from_branch: str = "main") -> Any:
        return self._req("POST", f"/graphs/{graph}/branches",
                         json_body={"name": name, "from": from_branch}).json()

    def branch_delete(self, graph: str, name: str) -> Any:
        return self._req("DELETE", f"/graphs/{graph}/branches/{name}").json()

    def branch_merge(self, graph: str, source: str, target: str = "main") -> Any:
        return self._req("POST", f"/graphs/{graph}/branches/merge",
                         json_body={"source": source, "target": target}).json()

    def commits(self, graph: str, branch: str = "main") -> list[dict]:
        raw = self._req("GET", f"/graphs/{graph}/commits",
                        params={"branch": branch}).json()
        if isinstance(raw, dict):
            return raw.get("commits", raw.get("data", []))
        return raw if isinstance(raw, list) else []
