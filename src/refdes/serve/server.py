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
import re
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from .. import calc
from ..build import INLINE_VALUE_RE
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


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(r'\bsrc="([^"]*)"', re.IGNORECASE)
# The content-hash segment `_hashed_leaf` appends: 16 hex digits before the
# extension of the assets/-relative destination.
_HASH_LEAF_RE = re.compile(r"\.([0-9a-f]{16})\.[^.]+$")


def _decorate_images(page: str, project, item) -> str:
    """Thread workbench W2 (D2): image provenance on the previewed item's own
    `<img>` tags, from the results `build._process_images` already recorded.
    A resolved image gets its source path and content hash as hover-visible
    attributes; one the build could not resolve (missing or ambiguous) gets a
    visible inline marker instead of rendering as a silent broken image
    (docs/design/thread-workbench.md §1, "Images are queries, not paths").
    Response-only, like the toolbar: the generation on disk stays the
    published page. Nothing here resolves anything -- it reads what the
    build decided."""
    results = project.image_results.get(item.id)
    if not results:
        return page
    provenance = {}
    failed = set()
    for r in results:
        if r["ok"]:
            provenance["assets/" + r["dest"]] = r["rel"]
        else:
            failed.add(r["src"])

    def swap(match: re.Match) -> str:
        tag = match.group(0)
        src_attr = _SRC_ATTR_RE.search(tag)
        if src_attr is None:
            return tag
        src = src_attr.group(1)
        if src in failed:
            return tag + (
                '<span class="refdes-squiggle bad mono small">'
                f"refdes: image {html_mod.escape(repr(src), quote=False)} did not resolve"
                " — see the Diagnostics panel</span>"
            )
        rel = provenance.get(src)
        if rel is None:
            return tag
        digest = _HASH_LEAF_RE.search(src.rpartition("/")[2])
        shown = f"{rel} · {digest.group(1)}" if digest else rel
        attrs = (
            f' data-refdes-src="{html_mod.escape(rel, quote=True)}"'
            f' title="{html_mod.escape(shown, quote=True)}"'
        )
        end = src_attr.end()
        return tag[:end] + attrs + tag[end:]

    return _IMG_TAG_RE.sub(swap, page)


_CODE_ELEM_RE = re.compile(r"<code\b[^>]*>.*?</code>", re.DOTALL)
_PRE_REGION_RE = re.compile(r"<pre\b[\s\S]*?</pre>", re.IGNORECASE)
_CALC_TABLE_RE = re.compile(r'<table class="calc"[\s\S]*?</table>', re.IGNORECASE)


def _esc_code(text: str) -> str:
    # What markdown-it leaves inside an inline code span: only these three
    # characters are escaped there, so this is the comparison the W3 walk needs.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _diagnostics_panel(project, item) -> str:
    """Thread workbench W2 (D3): this item's own build diagnostics, rendered
    in the response of its preview page. Filtered to the item by id or by its
    own source file -- the same file:line-shaped data `refdes build` prints
    and the index page lists, in the index page's own markup
    (`templates/index.html.j2`). Response-only decoration like everything
    else here."""
    diags = [
        d
        for d in project.diagnostics
        if d.item_id == item.id or (d.file and d.file == item.source_file)
    ]
    if not diags:
        return ""
    lis = "".join(
        f'<li class="{"bad" if d.level == "error" else "warn"}">'
        f"{html_mod.escape(d.level)} — {html_mod.escape(d.where)}"
        + (f" [{html_mod.escape(d.item_id)}]" if d.item_id else "")
        + f": {html_mod.escape(d.message)}</li>"
        for d in diags
    )
    return (
        '<section class="refdes-diags panel">'
        "<h2>Diagnostics for this item</h2>"
        f'<ul class="tight mono small">{lis}</ul>'
        "</section>"
    )


# The W3 toggle: one button per calc table, shown only when the page carries
# at least one value attribution. `preview.js` flips `refdes-values-off` on
# the root element; `bar.css` does the hiding. No semantics -- the badge
# content was decided by the build; the toggle only flips visibility.
_VALUES_TOGGLE = (
    '<button type="button" class="refdes-values-toggle" aria-pressed="true">'
    "values</button>"
)


def _add_values_toggle(page: str) -> str:
    out = []
    last = 0
    for match in _CALC_TABLE_RE.finditer(page):
        out.append(page[last : match.start()])
        table = match.group(0)
        if 'class="calc-caption"' in table:
            table = table.replace("</caption>", _VALUES_TOGGLE + "</caption>", 1)
        else:
            open_end = table.index(">") + 1
            caption = '<caption class="calc-caption refdes-only">' + _VALUES_TOGGLE + "</caption>"
            table = table[:open_end] + caption + table[open_end:]
        out.append(table)
        last = match.end()
    out.append(page[last:])
    return "".join(out)


def _decorate_calc_values(page: str, item) -> str:
    """Thread workbench W3 (D1, docs/design/thread-workbench.md §7.1): the
    published page already renders every `{{name}}` prose reference as its
    evaluated value -- as a bare <code> span with the name destroyed. The
    pane puts the name back beside the value (D1's "name as attribution"),
    plus the owning block's name for free from `CalcLine.block`
    (docs/design/named-calc-blocks.md §5.5). Response-only like every other
    decoration here; the values come from `item.calc_values`, the strings
    the build already formatted -- nothing is evaluated or re-evaluated.

    Identification is a parallel walk, not a guess: the build substituted
    INLINE_VALUE_RE over the body in document order, so the k-th surviving
    reference's value is the k-th matching <code> element in the page. The
    walk only advances on an exact text match, so an author's own code span
    (any text that is not the current expected value) is left untouched.
    `{{name | unit}}` references are deliberately skipped: their rendered
    text is a build-time conversion stored nowhere, and recomputing it would
    be re-evaluation. A code span whose text coincides with the current
    expected value can be decorated; the attribution it shows is still a
    real build fact."""
    body = calc.CALC_BLOCK_RE.sub("", item.body)
    refs = [
        m.group(1)
        for m in INLINE_VALUE_RE.finditer(body)
        if not (m.group(2) or "").strip() and m.group(1) in item.calc_values
    ]
    if not refs:
        return page
    blocks = {}
    for line in item.calcs:
        blocks.setdefault(line.name, line.block)
    pre_regions = [m.span() for m in _PRE_REGION_RE.finditer(page)]
    cursor = [0]
    decorated = [0]

    def swap(match: re.Match) -> str:
        i = cursor[0]
        if i >= len(refs):
            return match.group(0)
        name = refs[i]
        tag = match.group(0)
        open_end = tag.index(">") + 1
        inner = tag[open_end:-len("</code>")]
        if inner != _esc_code(item.calc_values[name]):
            return tag
        cursor[0] += 1
        decorated[0] += 1
        block = blocks.get(name, "")
        title = f"{name} = {item.calc_values[name]}"
        if block:
            title += f" (block: {block})"
        attrs = (
            f' data-refdes-calc="{html_mod.escape(name, quote=True)}"'
            f' title="{html_mod.escape(title, quote=True)}"'
        )
        badge = ""
        if not any(start <= match.start() < end for start, end in pre_regions):
            label = f"{name} · {block}" if block else name
            badge = f'<span class="refdes-calc-attr">{html_mod.escape(label)}</span>'
        return tag[: open_end - 1] + attrs + ">" + tag[open_end:] + badge

    page = _CODE_ELEM_RE.sub(swap, page)
    if decorated[0]:
        page = _add_values_toggle(page)
    return page


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
        project = self.app.state.snapshot.project
        links = ['<a href="/edit/">Editor</a>']
        item = None
        for key, slug_file in api.item_pages(project).items():
            if slug_file == filename:
                href = html_mod.escape("/edit/#/items/" + quote(key, safe=""))
                links.append(f'<a href="{href}">Edit this item</a>')
                item = project.items[key]
                break
        if item is not None:
            page = _decorate_images(page, project, item)
            page = _decorate_calc_values(page, item)
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
        panel = _diagnostics_panel(project, item) if item is not None else ""
        body_at = lower.rfind("</body>")
        page = (
            page[:body_at] + panel + bar + page[body_at:]
            if body_at != -1
            else page + panel + bar
        )
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
