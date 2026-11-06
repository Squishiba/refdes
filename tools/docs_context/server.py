"""docs context viewer (DC-2): a read-only local web page over DC-1's cards.

Serves one docs page (given on the command line) so it can sit open beside
the editor: the left column is the page's blocks, the right column the card
refs.py resolved for every reference in the selected block, with broken refs
flagged. Each card carries three ask buttons (explain / misread / match)
answered by a local model as a READING AID: ``POST /api/ask`` takes only a
block line, a ref index and a question name, builds the prompt from the
server's own current analysis via ``llm.build_messages``, and the browser
can never supply prompt text. ``POST /api/focus`` takes an editor cursor
``{path, line}`` and remembers, IN MEMORY ONLY, the block under that line of
the served doc (any other path is answered by string comparison alone, never
opened); the page polls ``GET /api/focus`` so the viewer can follow the
cursor. Stdlib only; binds 127.0.0.1; writes nothing;
the only outbound connection is the LLM request, whose url is refused at
startup unless it is loopback. Path safety lives in ``refs.py`` -- this
module imports it and never copies its checks.

Run: ``python tools/docs_context/server.py <doc.md> [--repo ROOT] [--port N]
[--no-open] [--llm-url URL] [--llm-model ID]``. The default ``--repo`` is
found upward from the doc (a ``.git`` directory or ``refdes-project.yaml``),
else the doc's parent. Port 0 (the default) picks an ephemeral one; the
listening URL is printed once, on stdout, as the only stdout line.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:
    from docs_context import llm, refs
    from docs_context.llm import DEFAULT_LLM_URL, require_loopback
except ModuleNotFoundError:  # run as a script from a checkout, tools/ not on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from docs_context import llm, refs
    from docs_context.llm import DEFAULT_LLM_URL, require_loopback

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
ASK_MAX_BODY = 4096
ASK_ORIGINS = ("http://127.0.0.1", "http://localhost", "http://[::1]")
FOCUS_MAX_BODY = 1024
FOCUS_MAX_LINE = 10_000_000


class DocState:
    """The served doc, the repo it resolves in, the analyze cache, the LLM
    endpoint the ask buttons post to (loopback, validated at startup), the
    one-at-a-time lock around the model, and the in-memory focus the editor
    posts (lock-protected; nothing about it is ever written to disk)."""

    def __init__(
        self,
        doc_path: str,
        repo_root: str,
        llm_url: str = DEFAULT_LLM_URL,
        llm_model: str | None = None,
    ) -> None:
        require_loopback(llm_url)  # before anything can use it
        self.repo_root = os.path.abspath(repo_root)
        self.repo_real = os.path.realpath(self.repo_root)
        self.doc_abs = os.path.abspath(doc_path)
        inside, rel = refs._inside_repo(self.repo_real, os.path.realpath(self.doc_abs))
        if not inside:
            raise ValueError(f"doc is outside the repo: {doc_path}")
        self.rel_doc = Path(rel).as_posix()
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.ask_lock = threading.Lock()
        self._cache: dict[str, tuple[tuple[int, int], dict]] = {}
        self.focus_lock = threading.Lock()
        self.focus_seq = 0
        self.focus_line: int | None = None
        self.focus_block: int | None = None

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

    def focus_payload(self) -> dict:
        """GET /api/focus: the remembered focus. Reads in-memory fields only
        -- it never parses the doc -- and the path is always the served
        doc's repo-relative path (the spec types it str; nulls are line/block
        only)."""
        with self.focus_lock:
            return {
                "seq": self.focus_seq,
                "line": self.focus_line,
                "block": self.focus_block,
                "path": self.rel_doc,
            }

    def block_at(self, line: int) -> int | None:
        """The start_line of the block containing LINE, else of the nearest
        block starting at or before it, else of the first block; a line past
        the last block clamps to the last. Computed at POST time from the
        same (mtime_ns, size) cache /api/doc uses: an unchanged file resolves
        nothing, an edited file's POST reflects the NEW analysis."""
        blocks = self.doc_payload(self.rel_doc)["blocks"]
        chosen = None
        for block in blocks:
            if block["start_line"] <= line:
                chosen = block
            else:
                break
        if chosen is None and blocks:
            chosen = blocks[0]
        return chosen["start_line"] if chosen is not None else None

    def accept_focus(self, line: int) -> dict:
        """Record an accepted focus in memory: seq increments on every
        accepted POST (the same line twice included; the UI de-dupes by
        block)."""
        block = self.block_at(line)
        with self.focus_lock:
            self.focus_seq += 1
            self.focus_line = line
            self.focus_block = block
        return {"followed": True, "line": line, "block": block}

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
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, "application/json", json.dumps(payload).encode("utf-8"))

    def _static(self, name: str) -> None:
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
        if self.command == "POST":
            # POST is only ever the ask and focus routes; every other POST is a 405.
            if path == "/api/ask":
                self._ask(state)
            elif path == "/api/focus":
                self._focus(state)
            else:
                self._method_not_allowed()
            return
        if path == "/api/ask":
            # the ask route is POST-only, on every method word
            self._json(405, {"error": "method not allowed"})
            return
        if path == "/api/focus":
            # the focus state is in memory: the GET reads fields, never parses
            self._json(200, state.focus_payload())
            return
        qs = parse_qs(query, keep_blank_values=True)
        if path == "/":
            self._static("index.html")
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
            if STATIC_NAME_RE.fullmatch(name) is None:
                self._json(404, {"error": "not found"})
            else:
                self._static(name)
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

    def _read_ask_body(self) -> bytes | None:
        """The POST body, fully drained from the wire (a keep-alive
        connection must not desync), or None when this responded already:
        a chunked body cannot be drained by length, and a body past
        DRAIN_MAX gets the response plus a close."""
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            self._json(400, {"error": "chunked bodies are not accepted"})
            return None
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw) if raw is not None else 0
        except ValueError:
            length = 0
        if length > DRAIN_MAX:
            self.close_connection = True
            self._json(400, {"error": "body too large"})
            return None
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _json_post(self, max_body: int) -> bytes | None:
        """The shared guards of the JSON POST routes (/api/ask, /api/focus):
        the X-Docs-Context header, the absent-or-own Origin, the JSON
        Content-Type, and a fully drained body within max_body bytes. The
        bytes of the body, or None when this responded already."""
        if self.headers.get("X-Docs-Context") != "1":
            self._drain_body()
            self._json(403, {"error": "forbidden"})
            return None
        origin = self.headers.get("Origin")
        port = str(self.server.server_address[1])
        if origin is not None and origin not in {f"{scheme}:{port}" for scheme in ASK_ORIGINS}:
            self._drain_body()
            self._json(403, {"error": "forbidden"})
            return None
        ctype = self.headers.get("Content-Type", "")
        if ctype.split(";", 1)[0].strip().lower() != "application/json":
            self._drain_body()
            self._json(415, {"error": "application/json body required"})
            return None
        body = self._read_ask_body()
        if body is None:
            return None
        if len(body) > max_body:
            self._json(400, {"error": "body too large"})
            return None
        return body

    @staticmethod
    def _json_object(body: bytes) -> tuple[dict | None, str]:
        """(decoded object, error) of a POST body: the object and "" when it
        is a JSON object; (None, "json") for an undecodable body and
        (None, "object") for a JSON value that is not an object. Each caller
        answers the error with its own 400 text."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "json"
        if not isinstance(payload, dict):
            return None, "object"
        return payload, ""

    def _focus(self, state: DocState) -> None:
        """POST /api/focus: {"path": repo-relative posix path, "line": int
        1-based}. When the path names the served doc -- posix, case-sensitive,
        a leading ``./`` normalised, by STRING COMPARISON alone: the path is
        never opened, never resolved on disk -- the block under that line is
        remembered in memory (seq increments) and the reply is
        ``{"followed": true, "line": N, "block": B}``. Any other path
        (``..``, absolute, NUL and dot-prefixed lookalikes included) is
        answered ``{"followed": false, "reason": "other-doc"}`` and changes
        nothing, not even seq."""
        body = self._json_post(FOCUS_MAX_BODY)
        if body is None:
            return
        payload, error = self._json_object(body)
        if error == "json":
            self._json(400, {"error": "body must be json"})
            return
        if error == "object":
            self._json(400, {"error": "body must be a json object"})
            return
        raw_path = payload.get("path")
        line = payload.get("line")
        if not isinstance(raw_path, str):
            self._json(400, {"error": "path must be a string"})
            return
        if isinstance(line, bool) or not isinstance(line, int):
            self._json(400, {"error": "line must be an integer"})
            return
        if line < 1 or line > FOCUS_MAX_LINE:
            self._json(400, {"error": "line out of range"})
            return
        raw_rel = raw_path.removeprefix("./")
        if raw_rel != state.rel_doc:
            self._json(200, {"followed": False, "reason": "other-doc"})
            return
        self._json(200, state.accept_focus(line))

    def _ask(self, state: DocState) -> None:
        """POST /api/ask: {"block": start_line, "ref": index, "question": name}.
        Only the three fixed questions exist and only the server's own
        current analysis feeds the prompt; body keys other than these three
        are ignored, so no client-supplied prompt, text, or messages can
        reach the model. One request at a time (409 busy); LLM failures are
        502/504 with the LlmError kind."""
        body = self._json_post(ASK_MAX_BODY)
        if body is None:
            return
        payload, error = self._json_object(body)
        if error == "json":
            self._json(400, {"error": "body must be json"})
            return
        if error == "object":
            self._json(400, {"error": "body must be a json object"})
            return
        block_line = payload.get("block")
        ref_index = payload.get("ref")
        question = payload.get("question")
        if isinstance(block_line, bool) or not isinstance(block_line, int):
            self._json(400, {"error": "block must be an integer"})
            return
        if isinstance(ref_index, bool) or not isinstance(ref_index, int):
            self._json(400, {"error": "ref must be an integer"})
            return
        if not isinstance(question, str):
            self._json(400, {"error": "question must be a string"})
            return
        doc = state.doc_payload(state.rel_doc)
        block = None
        for candidate in doc["blocks"]:
            if candidate["start_line"] == block_line:
                block = candidate
                break
        if block is None:
            self._json(400, {"error": "no such block"})
            return
        block_refs = block.get("refs") or []
        if ref_index < 0 or ref_index >= len(block_refs):
            self._json(400, {"error": "no such ref in the block"})
            return
        ref = block_refs[ref_index]
        try:
            messages = llm.build_messages(question, block, ref, ref.get("card") or {})
        except ValueError:
            self._json(400, {"error": "unknown question"})
            return
        if not state.ask_lock.acquire(blocking=False):
            self._json(409, {"error": "busy"})
            return
        try:
            model = state.llm_model
            if model is None:
                model = llm.discover_model(state.llm_url)
            answer = llm.ask_model(messages, base_url=state.llm_url, model=model)
            self._json(200, {"answer": answer, "model": model, "question": question})
        except llm.LlmError as exc:
            status = 504 if exc.kind == "timeout" else 502
            self._json(status, {"error": str(exc), "kind": exc.kind})
        finally:
            state.ask_lock.release()

    def do_GET(self) -> None:
        self._guarded()

    def do_HEAD(self) -> None:
        self._guarded()

    def _drain_body(self) -> None:
        """Consume a request body so a keep-alive connection cannot desync:
        the 405/403 response must not leave the body to be parsed as the
        next request. A chunked body (framed, not drainable by length) and
        a Content-Length past the cap get the response plus a close."""
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            return
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

    def do_POST(self) -> None:
        self._guarded()  # only /api/ask routes; every other POST is a 405

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


def make_server(
    doc_path: str,
    repo_root: str,
    port: int = 0,
    llm_url: str | None = None,
    llm_model: str | None = None,
):
    """(httpd, base_url) bound to 127.0.0.1; caller runs serve_forever().

    A non-loopback ``llm_url`` raises ``ValueError`` here, before the
    server is created -- no socket is bound and no request can use it.
    """
    state = DocState(
        doc_path,
        repo_root,
        llm_url=DEFAULT_LLM_URL if llm_url is None else llm_url,
        llm_model=llm_model,
    )
    httpd = DocsContextServer(("127.0.0.1", port), DocsContextHandler)
    httpd.state = state
    base_url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    return httpd, base_url


def find_repo_upward(doc_path: Path) -> Path:
    start = doc_path.parent
    for directory in (start, *start.parents):
        if (
            (directory / ".git").exists()  # a worktree checkout has .git as a FILE
            or (directory / "refdes-project.yaml").is_file()
        ):
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
    parser.add_argument(
        "--llm-url",
        default=DEFAULT_LLM_URL,
        help="OpenAI-compatible base url for the ask buttons (default: "
        "http://127.0.0.1:8080/v1; loopback only -- 127.0.0.1, localhost, "
        "or ::1)",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="model id to ask (default: discovered from the llm's /models)",
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
    try:
        require_loopback(args.llm_url)
    except ValueError as exc:
        print(f"server: {exc}", file=sys.stderr)
        return 2

    httpd, base_url = make_server(
        str(doc), str(repo), port=args.port, llm_url=args.llm_url, llm_model=args.llm_model
    )
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
