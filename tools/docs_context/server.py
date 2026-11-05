"""docs context viewer (DC-2): a read-only local web page over DC-1's cards.

Serves one docs page (given on the command line) so it can sit open beside
the editor: the left column is the page's blocks, the right column the card
refs.py resolved for every reference in the selected block, with broken refs
flagged. Stdlib only; binds 127.0.0.1; GET/HEAD only; writes nothing; makes
no outbound connection. Path safety lives in ``refs.py`` -- this module
imports it and never copies its checks.

Run: ``python tools/docs_context/server.py <doc.md> [--repo ROOT] [--port N]
[--no-open]``. The default ``--repo`` is found upward from the doc (a ``.git``
directory or ``refdes-project.yaml``), else the doc's parent. Port 0 (the
default) picks an ephemeral one; the listening URL is printed once, on
stdout, as the only stdout line.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:
    from docs_context import refs
except ModuleNotFoundError:  # run as a script from a checkout, tools/ not on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from docs_context import refs

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}
FILE_WINDOW = 15
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
CACHE_MAX = 32
DRAIN_MAX = 1024 * 1024


class DocState:
    """The served doc, the repo it resolves in, and the analyze cache."""

    def __init__(self, doc_path: str, repo_root: str) -> None:
        self.repo_root = os.path.abspath(repo_root)
        self.repo_real = os.path.realpath(self.repo_root)
        self.doc_abs = os.path.abspath(doc_path)
        inside, rel = refs._inside_repo(self.repo_real, os.path.realpath(self.doc_abs))
        if not inside:
            raise ValueError(f"doc is outside the repo: {doc_path}")
        self.rel_doc = Path(rel).as_posix()
        self._cache: dict[str, tuple[tuple[int, int], dict]] = {}

    def target_for(self, rel: str) -> str:
        return os.path.join(self.repo_root, *rel.split("/"))

    def safe_doc_rel(self, raw: str) -> tuple[str | None, tuple[int, str] | None]:
        """Repo-relative .md page, or (None, (status, message)) -- 400 before
        any open, 404 only for a safe-shaped page that does not exist. The
        realpath check rejects symlinks out of the repo; refs.py's own
        posture, expressed here for the API's status codes."""
        if "\x00" in raw:
            return None, (400, "bad path")
        parts = re.split(r"[\\/]", raw)
        if any(part == ".." for part in parts) or any(part == ".git" for part in parts):
            return None, (400, "outside repo")
        if os.path.isabs(raw) or DRIVE_RE.match(raw):
            return None, (400, "absolute path not allowed")
        if not raw.lower().endswith(".md"):
            return None, (400, "not a markdown file")
        target = os.path.realpath(os.path.join(self.repo_real, raw))
        inside, rel = refs._inside_repo(self.repo_real, target)
        tail = target[len(self.repo_real):]
        if not inside or os.sep + ".git" + os.sep in tail or tail == os.sep + ".git":
            return None, (400, "outside repo")
        if not os.path.isfile(target):
            return None, (404, "no such page")
        return Path(rel).as_posix(), None

    def doc_payload(self, rel: str) -> dict:
        """refs.analyze's blocks for one page, cached by (mtime_ns, size)."""
        target = self.doc_abs if rel == self.rel_doc else self.target_for(rel)
        st = os.stat(target)
        key = (st.st_mtime_ns, st.st_size)
        cached = self._cache.get(rel)
        if cached is not None and cached[0] == key:
            return cached[1]
        analyzed = refs.analyze(target, self.repo_root)
        payload = {
            "doc": rel,
            "repo": Path(self.repo_root).as_posix(),
            "mtime": st.st_mtime,
            "blocks": analyzed["blocks"],
        }
        # dict order is insertion order: the oldest page is the first key.
        if len(self._cache) >= CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[rel] = (key, payload)
        return payload

    def mtime_payload(self) -> dict:
        return {"mtime": os.stat(self.doc_abs).st_mtime}

    def file_payload(self, raw: str, line: int) -> dict:
        """The +/-FILE_WINDOW window around one line, via refs' own reader."""
        try:
            lines, error = refs._read_text_file(self.repo_root, raw)
        except (OSError, ValueError):
            return {"path": raw, "error": "bad path"}
        if error == "missing":
            return {"path": raw, "exists": False}
        if error is not None:
            return {"path": raw, "exists": True, "error": error}
        low = max(1, line - FILE_WINDOW)
        high = min(len(lines), line + FILE_WINDOW)
        return {
            "path": raw,
            "exists": True,
            "lines": [{"n": n, "text": lines[n - 1]} for n in range(low, high + 1)],
        }


def _split_host(header: str) -> tuple[str, str]:
    """(host, port) of a Host header value; empty port when absent."""
    if header.startswith("["):
        host, _, rest = header[1:].partition("]")
        return host, rest[1:] if rest.startswith(":") else ""
    host, sep, port = header.rpartition(":")
    if sep and ":" not in host:
        return host, port
    return header, ""


class DocsContextHandler(BaseHTTPRequestHandler):
    server_version = "docs-context"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def _respond(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, "application/json", json.dumps(payload).encode("utf-8"))

    def _static(self, name: str, raw_name: str) -> None:
        path = STATIC_DIR / name
        try:
            # LF on the wire: the repo's static files are LF, and a Windows
            # checkout with core.autocrlf turns them into CRLF -- normalizing
            # keeps what browsers fetch byte-identical to what `read_text`
            # (universal newlines) reads in the contract tests.
            body = path.read_bytes().replace(b"\r\n", b"\n")
        except OSError:
            self._json(404, {"error": "not found"})
            return
        ctype = STATIC_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")
        self._respond(200, ctype, body)

    def _route(self) -> None:
        state: DocState = self.server.state
        path, _, query = self.path.partition("?")
        qs = parse_qs(query, keep_blank_values=True)
        if path == "/":
            self._static("index.html", "index.html")
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
            if STATIC_NAME_RE.fullmatch(name) is None:
                self._json(404, {"error": "not found"})
            else:
                self._static(name, name)
        elif path == "/api/doc":
            raw = qs.get("path", [None])[0]
            if raw is None:
                self._json(200, state.doc_payload(state.rel_doc))
                return
            rel, err = state.safe_doc_rel(raw)
            if err is not None:
                self._json(err[0], {"error": err[1]})
                return
            self._json(200, state.doc_payload(rel))
        elif path == "/api/mtime":
            self._json(200, state.mtime_payload())
        elif path == "/api/file":
            raw = qs.get("path", [None])[0]
            raw_line = qs.get("line", [None])[0]
            if raw is None or raw_line is None:
                self._json(400, {"error": "path and line are required"})
                return
            try:
                line = int(raw_line)
            except ValueError:
                self._json(400, {"error": "line must be an integer"})
                return
            self._json(200, state.file_payload(raw, line))
        else:
            self._json(404, {"error": "not found"})

    def do_GET(self) -> None:
        self._guarded()

    def do_HEAD(self) -> None:
        self._guarded()

    def _drain_body(self) -> None:
        """Consume a request body so a keep-alive connection cannot desync:
        the 405/403 response must not leave the body to be parsed as the
        next request. An oversized body gets the response plus a close
        instead of being buffered."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            return
        try:
            length = int(raw)
        except ValueError:
            length = 0
        if length > DRAIN_MAX:
            self.close_connection = True
            return
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _guarded(self) -> None:
        name, port = _split_host(self.headers.get("Host", ""))
        if name.lower() not in ALLOWED_HOSTS or port not in (
            "",
            str(self.server.server_address[1]),
        ):
            self._drain_body()
            self._json(403, {"error": "bad host"})
            return
        self._route()

    def _method_not_allowed(self) -> None:
        self._drain_body()
        self._json(405, {"error": "method not allowed"})

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_OPTIONS = _method_not_allowed

    def __getattr__(self, name: str):
        # Any method word the class does not name (TRACE, CONNECT, FOO, ...)
        # answers through the same 405 JSON path, never the stdlib 501.
        if name.startswith("do_"):
            return self._method_not_allowed
        raise AttributeError(name)


class DocsContextServer(ThreadingHTTPServer):
    daemon_threads = True


def make_server(doc_path: str, repo_root: str, port: int = 0):
    """(httpd, base_url) bound to 127.0.0.1; caller runs serve_forever()."""
    state = DocState(doc_path, repo_root)
    httpd = DocsContextServer(("127.0.0.1", port), DocsContextHandler)
    httpd.state = state
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    return httpd, base_url


def find_repo_upward(doc_path: Path) -> Path:
    start = doc_path.parent
    for directory in (start, *start.parents):
        if (directory / ".git").is_dir() or (directory / "refdes-project.yaml").is_file():
            return directory
    return start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="Serve a read-only web viewer for the references one "
        "docs page makes. Loopback only, GET only, writes nothing.",
    )
    parser.add_argument("doc", help="path to the docs page to serve")
    parser.add_argument(
        "--repo",
        default=None,
        help="repository root refs resolve against (default: found upward "
        "from the doc, else the doc's parent)",
    )
    parser.add_argument("--port", type=int, default=0, help="port to bind (default: ephemeral)")
    parser.add_argument(
        "--no-open", action="store_true", help="do not open a browser on startup"
    )
    args = parser.parse_args(argv)

    doc = Path(args.doc)
    if not doc.is_file():
        print(f"server: no such docs file: {args.doc}", file=sys.stderr)
        return 2
    if doc.suffix.lower() != ".md":
        print(f"server: not a markdown file: {args.doc}", file=sys.stderr)
        return 2
    repo = Path(args.repo) if args.repo is not None else find_repo_upward(doc)
    inside, _rel = refs._inside_repo(os.path.realpath(repo), os.path.realpath(doc))
    if not inside:
        print(f"server: the doc must live inside the repo root: {args.doc}", file=sys.stderr)
        return 2

    httpd, base_url = make_server(str(doc), str(repo), port=args.port)
    print(f"docs-context: http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
    if not args.no_open:
        with contextlib.suppress(Exception):
            webbrowser.open(base_url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
