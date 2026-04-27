#!/usr/bin/env python3
"""Minimal mock of the PersoIA API for CI smoke tests.

Implements just enough of the surface that `persoia login` exercises (the
only command that talks to the API directly via urllib — `chat` and `code`
shell out to aider, which is out of scope for the CI smoke):

  - POST /api/v1/cli/api-keys/login  → returns a fake api_key
  - GET  /v1/models                  → OpenAI-compatible model list
                                       (used as a readiness probe by the CI
                                       script before issuing the login)

The mock listens on 127.0.0.1:<port>. Run as a background process from CI.

Usage:
    python3 tests/mock_api.py --port 8765 &
    PERSOIA_API_BASE=http://127.0.0.1:8765/v1 \\
    PERSOIA_CONFIG=/tmp/login.env \\
    persoia login --email ci@example.com --password fake
    grep -q PERSOIA_API_KEY=persoia_demo_sk_mock_login /tmp/login.env
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

MOCK_API_KEY = "persoia_demo_sk_mock_login_ci"
MOCK_MODEL_ID = "openai/persoia"
MOCK_TENANT_NAME = "Mock Tenant"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — http.server interface
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"data": [{"id": MOCK_MODEL_ID, "object": "model"}]})
            return
        self._send(404, {"error": {"message": f"unknown path: {self.path}"}})

    def do_POST(self) -> None:  # noqa: N802 — http.server interface
        if self.path.rstrip("/") == "/api/v1/cli/api-keys/login":
            # Drain the request body so the client doesn't block on the half-open
            # connection. We don't validate credentials — any non-empty body is OK.
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length:
                self.rfile.read(length)
            self._send(
                200,
                {
                    "success": True,
                    "data": {
                        "api_key": MOCK_API_KEY,
                        "tenant_name": MOCK_TENANT_NAME,
                        "model": MOCK_MODEL_ID,
                        "config": {
                            # Reuse the same mock host so subsequent calls stay local.
                            "api_base": f"http://127.0.0.1:{self.server.server_address[1]}/v1",
                        },
                    },
                },
            )
            return
        self._send(404, {"error": {"message": f"unknown path: {self.path}"}})

    def log_message(self, fmt: str, *args: object) -> None:
        # Quiet by default; uncomment for debugging:
        # sys.stderr.write("[mock] " + (fmt % args) + "\n")
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), Handler)
    print(f"mock-api listening on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
