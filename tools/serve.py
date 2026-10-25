#!/usr/bin/env python3
"""Tiny static server for the exported web build (local testing).

    python tools/serve.py [port] [root]

Adds the MIME types Godot's web export needs and logs nothing, so a browser
closing a big download early cannot take the server down.
"""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".wasm": "application/wasm",
        ".webp": "image/webp",
        ".pck": "application/octet-stream",
        ".mp3": "audio/mpeg",
        ".js": "text/javascript",
    }

    def log_message(self, fmt, *args):  # keep the console clean
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "web"
    handler = partial(Handler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"serving {root} on http://127.0.0.1:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
