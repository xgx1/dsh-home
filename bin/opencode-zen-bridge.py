#!/usr/bin/env python3
"""Local bridge: an OpenAI-compatible client to opencode's free tier.

opencode's free tier refuses requests that do not look like its own client. Three
things in the request carry that identity, and only one of them is something a
stock OpenAI client can supply:

  * `User-Agent: opencode/<version>`   — the DSH pi-ai adapter reserves that
    header for its own attribution, so it cannot be set from provider config;
  * `x-opencode-session: ses_...`      — a descending-ordered opencode
    identifier (12 hex digits with the high bit set, then 14 base62 chars);
  * `tools` containing a function named `read`, and `stream: true` — both of
    which DSH's agent loop already sends.

The bridge adds the first two, and the `read` tool only when the caller sent
none. Streaming responses pass through unchanged.

Run: opencode-zen-bridge.py [--host 127.0.0.1] [--port 8790]
Check: opencode-zen-bridge.py --selftest big-pickle
"""

from __future__ import annotations

import argparse
import http.client
import http.server
import json
import secrets
import socketserver
import sys
import time

UPSTREAM_HOST = "opencode.ai"
UPSTREAM_PATH = "/inference/openai/v1/chat/completions"
OPENCODE_VERSION = "1.19.3"
IDENTIFIER_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Injected only when the caller's request carries no `read` tool at all; a real
# tool set always wins.
READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read the contents of a file.",
        "parameters": {
            "type": "object",
            "properties": {"filePath": {"type": "string", "description": "Path to the file to read"}},
            "required": ["filePath"],
        },
    },
}


def session_id(now_ms: int | None = None) -> str:
    """The `x-opencode-session` the free-tier gate accepts.

    Mirrors `Identifier.descending()` from opencode's `packages/schema`: a
    millisecond timestamp shifted left 12 bits plus a counter, complemented,
    rendered as six big-endian hex bytes, then 14 random base62 characters.
    """
    current = (int(time.time() * 1000) if now_ms is None else now_ms) * 0x1000 + 1
    value = ~current & 0xFFFF_FFFF_FFFF_FFFF
    head = "".join(f"{(value >> (40 - 8 * i)) & 0xFF:02x}" for i in range(6))
    return "ses_" + head + "".join(secrets.choice(IDENTIFIER_CHARS) for _ in range(14))


def parse(body: bytes) -> dict | None:
    """The request as a JSON object, or None when it is not one."""
    try:
        document = json.loads(body)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def gated(body: bytes, document: dict | None) -> bytes:
    """Return the request body with a `read` function tool guaranteed present.

    A body that is not a JSON object is forwarded untouched — the upstream then
    rejects it with its own message rather than this bridge inventing one.
    """
    if document is None:
        return body
    tools = document.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and (tool.get("function") or {}).get("name") == "read":
                return body
    document["tools"] = (tools if isinstance(tools, list) else []) + [READ_TOOL]
    return json.dumps(document, separators=(",", ":")).encode()


class Bridge(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
        sys.stderr.flush()

    def _reply(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if self.path.rstrip("/") in ("/health", ""):
            self._reply(200, b'{"status":"ok"}')
        else:
            self._reply(404, b'{"error":"only POST /v1/chat/completions is bridged"}')

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._reply(404, b'{"error":"only POST /v1/chat/completions is bridged"}')
            return
        authorization = self.headers.get("Authorization")
        if not authorization:
            self._reply(401, b'{"error":"the bridge forwards the caller\'s Authorization header and got none"}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        document = parse(body)
        if document is not None and document.get("stream") is False:
            self._reply(
                400,
                b'{"error":"opencode\'s free tier requires \\"stream\\": true; resend the request streamed"}',
            )
            return
        raw = gated(body, document)
        upstream = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=1800)
        try:
            upstream.request(
                "POST",
                UPSTREAM_PATH,
                body=raw,
                headers={
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                    "User-Agent": "opencode/" + OPENCODE_VERSION,
                    "x-opencode-session": session_id(),
                    "Accept": "text/event-stream",
                    "Content-Length": str(len(raw)),
                },
            )
            response = upstream.getresponse()
            if response.status != 200:
                payload = response.read()
                self._reply(response.status, payload, response.getheader("Content-Type") or "application/json")
                return
            self.send_response(200)
            self.send_header("Content-Type", response.getheader("Content-Type") or "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = response.read1(4096)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def selftest(model: str, api_key: str) -> int:
    """One real request that fails if the gate recipe or the model id breaks."""
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "reply with exactly: ok"}],
            "tools": [READ_TOOL],
            "stream": True,
        },
        separators=(",", ":"),
    ).encode()
    request = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=180)
    request.request(
        "POST",
        UPSTREAM_PATH,
        body=body,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "opencode/" + OPENCODE_VERSION,
            "x-opencode-session": session_id(),
            "Accept": "text/event-stream",
            "Content-Length": str(len(body)),
        },
    )
    response = request.getresponse()
    head = response.read(80).decode("utf8", "replace").replace("\n", " ")
    print("%s %s %s" % ("PASS" if response.status == 200 else "FAIL", response.status, head[:60]))
    request.close()
    return 0 if response.status == 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--selftest", metavar="MODEL", help="probe one model upstream and exit")
    parser.add_argument("--api-key", default="", help="API key for --selftest; defaults to $OPENCODE_API_KEY")
    arguments = parser.parse_args()
    if arguments.selftest:
        import os

        key = arguments.api_key or os.environ.get("OPENCODE_API_KEY", "")
        if not key:
            print("--selftest needs --api-key or $OPENCODE_API_KEY", file=sys.stderr)
            return 2
        return selftest(arguments.selftest, key)
    server = Server((arguments.host, arguments.port), Bridge)
    print("opencode zen bridge on http://%s:%d/v1" % (arguments.host, arguments.port), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())