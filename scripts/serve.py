"""Serve the static site locally: python scripts/serve.py [port]"""
import functools
import http.server
import sys
from pathlib import Path

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
site = Path(__file__).resolve().parents[1] / "site"
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
print(f"Entropy XI site: http://localhost:{port}/")
http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
