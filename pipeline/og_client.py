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
        body: dict = {"branch": branch}
        if type_names:
            body["type_names"] = type_names
        r = self._req("POST", f"/graphs/{graph}/export", json_body=body, stream=True)
        rows: list[dict] = []
        for line in r.iter_lines():
            if line:
                rows.append(json.loads(line))
        return rows

    # ── writes (Cedar-gated server-side) ────────────────────
    def load(self, graph: str, ndjson_lines: Iterable[str], *,
             branch: str, from_branch: Optional[str] = None,
             mode: str = "merge") -> Any:
        body: dict = {"data": "\n".join(ndjson_lines), "branch": branch, "mode": mode}
        if from_branch:
            body["from"] = from_branch
        return self._req("POST", f"/graphs/{graph}/load", json_body=body).json()

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
    def branches(self, graph: str) -> Any:
        return self._req("GET", f"/graphs/{graph}/branches").json()

    def branch_create(self, graph: str, name: str, from_branch: str = "main") -> Any:
        return self._req("POST", f"/graphs/{graph}/branches",
                         json_body={"name": name, "from": from_branch}).json()

    def branch_delete(self, graph: str, name: str) -> Any:
        return self._req("DELETE", f"/graphs/{graph}/branches/{name}").json()

    def branch_merge(self, graph: str, source: str, target: str = "main") -> Any:
        return self._req("POST", f"/graphs/{graph}/branches/merge",
                         json_body={"source": source, "target": target}).json()

    def commits(self, graph: str, branch: str = "main") -> Any:
        return self._req("GET", f"/graphs/{graph}/commits",
                         params={"branch": branch}).json()
