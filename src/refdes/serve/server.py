"""The stdlib HTTP server behind `refdes serve`.

Routing, in order of what a request must clear:

1. `Host` must be an accepted loopback host:port -- before anything else, so a
   DNS-rebinding request reveals nothing, not even a 404 shape;
2. `/api/*` needs the launch token in `X-Refdes-Token` (reads too); a POST also
   needs a matching `Origin`, a JSON content type, and a bounded body;
3. every other surface (`/preview/`, `/edit/`) needs the session cookie, which
   only the launch URL (`/?token=...`) sets -- `SameSite=Strict`, `HttpOnly`,
   then a redirect that strips the token from the address bar.

No endpoint takes a filesystem path from the client. Preview and static files
are found by segment-checked lookup below fixed roots only.
"""

from __future__ import annotations

import html as html_mod
import json
import mimetypes
import os
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from . import api, security
from .preview import PreviewManager
from .state import Poller, ProjectState

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY_BYTES = 1024 * 1024
_STATIC_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
}
_BAR_HEAD = '<link rel="stylesheet" href="/edit/static/bar.css">'


def _reload_probe(token: str, serial: int) -> str:
    """The W1 auto-reload probe (docs/design/thread-workbench.md): the serial
    of the snapshot being served, the launch token (the same meta the editor
    shell carries -- the page is already cookie-gated on that token), and the
    module that polls /api/revision and reloads when the serial moves. Like
    the toolbar, this lives only in the HTTP response, never in the rendered
    files."""
    return (
        f'<meta name="refdes-token" content="{html_mod.escape(token, quote=True)}">'
        f'<meta name="refdes-serial" content="{int(serial)}">'
        '<script type="module" src="/edit/static/preview.js"></script>'
    )


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # never share a port with a stale listener
    app: EditorApp


class EditorApp:
    """One project, one process: the loaded state, the preview, the listener."""

    def __init__(
        self,
        config_path: str | None,
        temp_dir: str | None = None,
        poll_interval: float = 1.0,
        read_only: bool = False,
    ):
        self.token = security.new_token()
        self.read_only = read_only
        self.preview = PreviewManager(temp_dir)
        try:
            self.state = ProjectState(config_path, self.preview)
            self.state.load()
            # IPv4 loopback only, ephemeral port (0): never a host argument.
            self.httpd = _Server((security.LOOPBACK_ADDRESS, 0), _Handler)
        except BaseException:
            self.preview.close()
            raise
        self.httpd.app = self
        self.port: int = self.httpd.server_address[1]
        self.poller = Poller(self.state, interval=poll_interval)
        self._thread: threading.Thread | None = None

    @property
    def launch_url(self) -> str:
        return f"http://{security.LOOPBACK_ADDRESS}:{self.port}/?{urlencode({'token': self.token})}"

    def start(self) -> None:
        self.poller.start()
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
        )
        self._thread.start()

    def serve_forever(self) -> None:
        self.poller.start()
        self.httpd.serve_forever(poll_interval=0.2)

    def stop(self) -> None:
        self.poller.stop()
        if self._thread is not None:
            self.httpd.shutdown()
            self._thread.join(timeout=5)
        self.httpd.server_close()
        self.preview.close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "refdes-serve"
    sys_version = ""
    timeout = 30

    @property
    def app(self) -> EditorApp:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format, *args):
        # The request line can carry the launch token; log nothing.
        pass

    # ------------------------------------------------------------- plumbing

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        csp: str = security.EDITOR_CSP,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in security.security_headers(csp).items():
            self.send_header(name, value)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
        self._send(status, body.encode("utf-8"), "application/json; charset=utf-8")

    def _deny(self, status: int, message: str) -> None:
        self._send(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _cookie_ok(self) -> bool:
        raw = self.headers.get("Cookie")
        if not raw:
            return False
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed Cookie header is just a miss
            return False
        morsel = jar.get(security.cookie_name(self.app.port))
        return morsel is not None and security.tokens_equal(morsel.value, self.app.token)

    # -------------------------------------------------------------- methods

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._deny(405, "method not allowed")

    do_DELETE = do_PATCH = do_PUT

    def _dispatch(self) -> None:
        app = self.app
        if not security.host_ok(self.headers.get("Host"), app.port):
            return self._deny(403, "forbidden")
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        origin = self.headers.get("Origin")
        if origin is not None and not security.origin_ok(origin, self.headers.get("Host"), app.port):
            return self._deny(403, "forbidden")
        if path.startswith("/api/") or path == "/api":
            return self._api(path, query)
        if self.command not in ("GET", "HEAD"):
            return self._deny(405, "method not allowed")

        supplied = query.get("token")
        if supplied and security.tokens_equal(supplied[0], app.token):
            return self._start_session(path, query)
        if not self._cookie_ok():
            return self._deny(403, "missing or invalid launch token")

        if path == "/":
            return self._redirect("/preview/")
        if path == "/preview" or path.startswith("/preview/"):
            return self._preview(path[len("/preview"):])
        if path in ("/edit", "/edit/", "/edit/index.html"):
            return self._shell()
        if path.startswith("/edit/static/"):
            return self._static(path[len("/edit/static/"):])
        return self._deny(404, "not found")

    def _redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        self._send(302, b"", "text/plain; charset=utf-8", headers={"Location": location, **(headers or {})})

    def _start_session(self, path: str, query: dict[str, list[str]]) -> None:
        rest = {k: v for k, v in query.items() if k != "token"}
        location = path + ("?" + urlencode(rest, doseq=True) if rest else "")
        cookie = (
            f"{security.cookie_name(self.app.port)}={self.app.token}; "
            "Path=/; HttpOnly; SameSite=Strict"
        )
        self._redirect(location, {"Set-Cookie": cookie})

    # ------------------------------------------------------------- surfaces

    def _shell(self) -> None:
        with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as fh:
            html = fh.read().replace("__REFDES_TOKEN__", self.app.token)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, name: str) -> None:
        parts = security.safe_relative_parts(name)
        if not parts or len(parts) != 1:
            return self._deny(404, "not found")
        ext = os.path.splitext(parts[0])[1].lower()
        path = os.path.join(STATIC_DIR, parts[0])
        if ext not in _STATIC_TYPES or ext == ".html" or not os.path.isfile(path):
            return self._deny(404, "not found")
        with open(path, "rb") as fh:
            self._send(200, fh.read(), _STATIC_TYPES[ext])

    def _preview(self, rest: str) -> None:
        parts = security.safe_relative_parts(rest)
        if parts is None:
            return self._deny(404, "not found")
        if not parts:
            parts = ["index.html"]
        fh = self.app.preview.open_file(parts)
        if fh is None:
            return self._deny(404, "not found")
        with fh:
            data = fh.read()
        name = parts[-1]
        if name.endswith(".html"):
            data = self._decorate(data, name)
            ctype = "text/html; charset=utf-8"
        else:
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send(200, data, ctype, csp=security.PREVIEW_CSP)

    def _decorate(self, data: bytes, filename: str) -> bytes:
        """Inject the server-only editor toolbar into a preview page's HTTP
        response. It is never written into the rendered files (Option A's
        boundary): a published `_site/` has no edit affordance at all."""
        try:
            page = data.decode("utf-8")
        except UnicodeDecodeError:
            return data
        links = ['<a href="/edit/">Editor</a>']
        for key, slug_file in api.item_pages(self.app.state.snapshot.project).items():
            if slug_file == filename:
                href = html_mod.escape("/edit/#/items/" + quote(key, safe=""))
                links.append(f'<a href="{href}">Edit this item</a>')
                break
        bar = (
            '<div class="refdes-serve-bar"><span>refdes serve &middot; preview</span>'
            + "".join(links)
            + "</div>"
        )
        probe = _reload_probe(self.app.token, self.app.state.snapshot.serial)
        lower = page.lower()
        head_at = lower.rfind("</head>")
        if head_at != -1:
            page = page[:head_at] + _BAR_HEAD + probe + page[head_at:]
            lower = page.lower()
        body_at = lower.rfind("</body>")
        page = page[:body_at] + bar + page[body_at:] if body_at != -1 else page + bar
        return page.encode("utf-8")

    # ------------------------------------------------------------------ api

    def _api(self, path: str, query: dict[str, list[str]]) -> None:
        app = self.app
        if not security.tokens_equal(self.headers.get(security.TOKEN_HEADER), app.token):
            return self._deny(403, "missing or invalid launch token")
        body = None
        if self.command == "POST":
            if not security.origin_ok(self.headers.get("Origin"), self.headers.get("Host"), app.port):
                return self._deny(403, "forbidden")
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._deny(415, "expected application/json")
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                return self._deny(411, "Content-Length required")
            if length < 0 or length > MAX_BODY_BYTES:
                return self._deny(413, "request too large")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"error": "invalid JSON"})
        elif self.command not in ("GET", "HEAD"):
            return self._deny(405, "method not allowed")
        status, payload = api.handle(app, self.command, path, query, body)
        self._json(status, payload)
