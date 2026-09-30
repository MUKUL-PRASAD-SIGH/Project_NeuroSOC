"""Backend for the example rewards campaign: serves the page and decides claims server-side.

    python sdk/examples/rewards-campaign/server.py        # http://localhost:5500

The claim decision uses the NeuroSOC secret key to look up the browser session's verdict, the
pattern every real integration should follow: shadowed sessions are told "pending review" and are
never paid. Standard library only, plus the neurosoc package from sdk/python.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SDK_ROOT = HERE.parents[1]
sys.path.insert(0, str(SDK_ROOT / "python"))

from neurosoc import NeuroSOC, NeuroSOCError  # noqa: E402

ENDPOINT = os.getenv("NEUROSOC_ENDPOINT", "http://localhost:8000")
PUBLISHABLE_KEY = os.getenv("NEUROSOC_PUBLISHABLE_KEY", "pk_local_example_campaign")
SECRET_KEY = os.getenv("NEUROSOC_SECRET_KEY", "sk_local_example_campaign_not_for_production")
PORT = int(os.getenv("PORT", "5500"))
REWARD = 25

soc = NeuroSOC(ENDPOINT, SECRET_KEY)
ledger = {"paid": 0, "withheld": 0, "paid_tokens": 0, "wallets": set()}
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            page = (HERE / "index.html").read_text(encoding="utf-8")
            page = page.replace("{{PUBLISHABLE_KEY}}", PUBLISHABLE_KEY).replace("{{ENDPOINT}}", ENDPOINT)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/sdk.js":
            bundle = SDK_ROOT / "js" / "dist" / "neurosoc.min.js"
            if not bundle.exists():
                self._send(503, b"// build the SDK first: cd sdk/js && npm install && npm run build", "text/javascript")
                return
            self._send(200, bundle.read_bytes(), "text/javascript; charset=utf-8")
        elif self.path == "/stats":
            with lock:
                self._json(200, {k: (len(v) if isinstance(v, set) else v) for k, v in ledger.items()})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/claim":
            self._send(404, b"not found", "text/plain")
            return
        length = min(int(self.headers.get("Content-Length") or 0), 10_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "bad request"})
            return
        session, wallet = str(body.get("session") or ""), str(body.get("wallet") or "")
        try:
            verdict = soc.session_verdict(session) if session else None
        except NeuroSOCError:
            verdict = None  # NeuroSOC unreachable: hold the claim rather than pay blindly
        with lock:
            if verdict is None or verdict.action in ("shadow", "step_up") or wallet in ledger["wallets"]:
                ledger["withheld"] += 1
                self._json(200, {"status": "pending_review"})
                return
            ledger["paid"] += 1
            ledger["paid_tokens"] += REWARD
            ledger["wallets"].add(wallet)
        self._json(200, {"status": "paid", "amount": REWARD})

    def log_message(self, format: str, *args) -> None:  # quieter console
        if "/claim" in (args[0] if args else ""):
            sys.stderr.write("claim %s\n" % (args[1] if len(args) > 1 else ""))


if __name__ == "__main__":
    print(f"Example campaign on http://localhost:{PORT}  (NeuroSOC at {ENDPOINT})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
