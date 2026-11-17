"""Local-only HTTP server for the UI.

Security model (this server can change hardware settings and inject input):
  * binds to 127.0.0.1 only;
  * every /api call needs the per-launch random token in X-Mouser-Token
    (a custom header also forces a CORS preflight, which we never approve);
  * Host must be our own loopback address (blocks DNS rebinding);
  * Origin, when sent, must be our own origin (blocks cross-site requests);
  * bodies are size-limited JSON and validated field by field;
  * static files come from a fixed allow-list, never from a client path.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Invalid
from .engine import Engine
from .razer import POLLING, RazerError

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}
MAX_BODY = 64 * 1024
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def make_server(engine: Engine, token: str, port: int, on_quit) -> ThreadingHTTPServer:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Mouser"
        sys_version = ""

        def log_message(self, *a):  # keep the console quiet
            pass

        # ---------- helpers ----------
        def _headers(self, code, ctype, length):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self._headers(code, "application/json", len(body))
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def _authed(self) -> bool:
            sent = self.headers.get("X-Mouser-Token", "")
            return self._host_ok() and hmac.compare_digest(sent.encode(), token.encode())

        def _body(self) -> dict:
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise Invalid("expected JSON")
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                raise Invalid("request body missing or too large")
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                raise Invalid("expected a JSON object")
            return data

        # ---------- routes ----------
        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            path, _, query = self.path.partition("?")
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(os.path.join(WEB_DIR, name), "rb") as f:
                    body = f.read()
                self._headers(200, ctype, len(body))
                return self.wfile.write(body)
            if path == "/api/ping":  # lets a second launch find the first
                return self._json(200, {"app": "mouser"})
            if not self._authed():
                return self._json(401, {"error": "This window is out of date. Reopen Mouser from the tray icon."})
            if path == "/api/state":
                return self._json(200, engine.full_state())
            if path == "/api/live":
                since = query[6:] if query.startswith("since=") else "0"
                return self._json(200, engine.live(int(since) if since.isdigit() and len(since) < 12 else 0))
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._authed():
                return self._json(401, {"error": "This window is out of date. Reopen Mouser from the tray icon."})
            path = self.path.split("?", 1)[0]
            try:
                b = self._body()
                if path == "/api/dpi":
                    x = _num(b.get("x"), 100, 26000)
                    y = _num(b.get("y", x), 100, 26000)
                    engine.set_dpi(x, y)
                elif path == "/api/stages":
                    st = b.get("stages")
                    if not isinstance(st, list) or not 1 <= len(st) <= 5:
                        raise Invalid("1 to 5 DPI stages")
                    stages = [(_num(s[0], 100, 26000), _num(s[1], 100, 26000)) for s in st if isinstance(s, list) and len(s) == 2]
                    if len(stages) != len(st):
                        raise Invalid("each stage is [x, y]")
                    engine.set_stages(stages, _num(b.get("active"), 1, len(stages)))
                elif path == "/api/polling":
                    hz = b.get("hz")
                    if hz not in POLLING:
                        raise Invalid("polling rate must be 125, 500 or 1000")
                    engine.set_polling(hz)
                elif path == "/api/lighting":
                    engine.set_lighting(b.get("zone"), b)
                elif path == "/api/scroll":
                    if b.get("key") not in ("free_spin", "acceleration", "smart_reel") or not isinstance(b.get("on"), bool):
                        raise Invalid("bad scroll setting")
                    engine.set_scroll(b["key"], b["on"])
                elif path == "/api/profiles":
                    engine.set_profiles(b.get("profiles"))
                elif path == "/api/clutch":
                    v = b.get("dpi")
                    engine.set_clutch_dpi(None if v is None else round(_num(v, 100, 26000) / 50) * 50)
                elif path == "/api/pause":
                    if not isinstance(b.get("paused"), bool):
                        raise Invalid("paused must be true or false")
                    engine.set_paused(b["paused"])
                elif path == "/api/quit":
                    self._json(200, {"ok": True})
                    return on_quit()
                else:
                    return self._json(404, {"error": "not found"})
            except Invalid as e:
                return self._json(400, {"error": str(e)})
            except RazerError as e:
                return self._json(503, {"error": f"The mouse didn't accept that: {e}"})
            except (ValueError, TypeError):
                return self._json(400, {"error": "malformed request"})
            return self._json(200, {"ok": True})

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv


def _num(v, lo, hi) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise Invalid(f"value must be between {lo} and {hi}")
    return int(v)
