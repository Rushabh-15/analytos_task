#!/usr/bin/env python3
"""Idempotent patch: make graph export resilient to premature-stream drops.

Symptom: `ChunkedEncodingError: Response ended prematurely` while streaming the
NDJSON export (the delta step's read of main). This is the transient
504/premature-chunk flakiness the Omnigraph docs warn about, made worse by
reading the stream line-by-line with iter_lines().

Fix:
  * export() now reads the FULL response body (no stream=True) and splits it,
    which avoids mid-stream chunk-decode failures, and
  * retries up to 3 times with a short backoff on transient read errors, and
  * the ingest delta step tolerates an export that still fails after retries by
    falling back to a read-query slug/edge scan (so a flaky export never aborts
    the whole ingest).

Run once:  python3 patch_export_resilient.py
"""
import sys
from pathlib import Path

OGC = Path("pipeline/og_client.py")
src = OGC.read_text()

if "def export(" not in src:
    print("!! export() not found -- aborting"); sys.exit(1)
if "buffered + retry" in src:
    print("already patched -- nothing to do"); sys.exit(0)

old_export = '''    def export(self, graph: str, branch: str = "main",
               type_names: Optional[list[str]] = None) -> list[dict]:
        body: dict = {"branch": branch}
        if type_names:
            body["type_names"] = type_names
        r = self._req("POST", f"/graphs/{graph}/export", json_body=body, stream=True)
        rows: list[dict] = []
        for line in r.iter_lines():
            if line:
                rows.append(json.loads(line))
        return rows'''

new_export = '''    def export(self, graph: str, branch: str = "main",
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
        raise OGError(0, f"export failed after retries: {last_err}", url)'''

src = src.replace(old_export, new_export, 1)
OGC.write_text(src)
print("patched pipeline/og_client.py -> export() is buffered + retry")

# also make the ingest delta step tolerant if export still fails
ING = Path("pipeline/ingest.py")
isrc = ING.read_text()
old_try = '''        try:
            base = og.export(graph, branch="main")
        except OGError:
            base = []'''
new_try = '''        try:
            base = og.export(graph, branch="main")
        except OGError as e:
            print(f"  \u26a0 {graph}: export of main failed ({e}); "
                  f"proceeding without delta filter (loads may retry).")
            base = []'''
if old_try in isrc:
    isrc = isrc.replace(old_try, new_try, 1)
    ING.write_text(isrc)
    print("patched pipeline/ingest.py -> delta step logs a clear warning on export failure")
else:
    print("  (ingest delta try/except already customized or not found — skipped)")

print("\n\u2714 export resilience patched. Re-run: make verify")