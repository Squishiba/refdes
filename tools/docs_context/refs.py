"""docs context refs (DC-1): read a docs page, emit a card per reference.

Parses a markdown page with the docs site's own parser
(``refdes.build._markdown_parser``), extracts the references each block
makes -- code refs (``src/refdes/cli.py:3227``), backticked file refs,
``refdes`` commands, and markdown links -- and resolves each one into a
JSON card of facts from the repository: the cited window of code, the
linked page's heading and excerpt, a command's own ``--help``.

Safety posture: read-only, no network. A referenced path is
``realpath``-checked against the repo root (and against ``.git/``)
*before* it is opened; anything that escapes is a card with an
``error``, never an ``open()``. Command cards run a subprocess only for
a verb path that ``refdes.cli.main``'s own argparse tree accepts, always
as a list argv with ``--help`` appended -- never a shell.

Stdlib + ``refdes`` only. Not a shipped package: run it as
``python tools/docs_context/refs.py <doc.md> [--repo ROOT]``.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import html
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import refdes.build as _build
    from refdes.cli import main as _refdes_main
    from refdes.pages import _slugify
    from refdes.parse import FRONTMATTER_RE
except ModuleNotFoundError:  # run as a script from a checkout, PYTHONPATH unset
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    import refdes.build as _build
    from refdes.cli import main as _refdes_main
    from refdes.pages import _slugify
    from refdes.parse import FRONTMATTER_RE

REFDES_SRC = str(Path(_build.__file__).resolve().parent.parent)

MAX_BYTES = 2 * 1024 * 1024
HEAD_BYTES = 8192
WINDOW = 5
FILE_HEAD_LINES = 12
HELP_CHARS = 4000
EXCERPT_LINES = 8

CONSOLE_LANGS = {"console", "sh", "bash", "shell", "shell-session", "zsh",
                 "powershell", "ps1", "cmd", "bat", "terminal", "text-console"}
METACHARS = set(';|&$<>()`{}*?!\'"\\\n\r')

CODE_SPAN_RE = re.compile(r"`+[^`\n]*`+")
LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\s]+)\)")
_PATH_SEG = r"(?!-)[\w.+-]+"
CODE_REF_RE = re.compile(
    rf"(?<![\w:/+\-.])({_PATH_SEG}(?:/{_PATH_SEG})+):(\d+)(?:-(\d+))?(?![\w+\-.])"
)
FILE_PATH_RE = re.compile(rf"{_PATH_SEG}(?:/{_PATH_SEG})+")
_VERB_RE = re.compile(r"[a-z][a-z0-9_-]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

_BLOCK_KINDS = {
    "heading_open": "heading",
    "paragraph_open": "paragraph",
    "list_item_open": "list_item",
    "table_open": "table",
}


@dataclass
class Ref:
    kind: str
    raw: str
    start: int
    end: int
    path: str = ""
    line_start: int = 0
    line_end: int = 0
    target: str = ""
    text: str = ""
    page: str | None = None
    anchor: str | None = None
    external: bool = False
    verbs: list[str] = field(default_factory=list)
    command: str = ""
    context: str = field(default="", repr=False)


@dataclass
class Block:
    kind: str
    start_line: int
    end_line: int
    text: str
    refs: list[Ref] = field(default_factory=list)


def parse_doc(text: str) -> list[Block]:
    """Split a docs page into blocks with line ranges and their refs."""
    lines = text.split("\n")
    tokens = _build._markdown_parser().parse(text, {})
    fenced = [
        (token.map[0], token.map[1])
        for token in tokens
        if token.type in ("fence", "code_block") and token.map is not None
    ]
    blocks: list[Block] = []
    in_list_item = 0
    for token in tokens:
        if token.type == "list_item_open":
            in_list_item += 1
        elif token.type == "list_item_close":
            in_list_item -= 1
            continue
        if token.type == "fence":
            kind = (
                "console"
                if token.info.strip().lower() in CONSOLE_LANGS
                else "code"
            )
        elif token.type == "paragraph_open" and in_list_item:
            continue  # the list_item block owns its inner paragraph
        else:
            kind = _BLOCK_KINDS.get(token.type, "")
        if not kind or token.map is None:
            continue
        start, end = token.map
        block = Block(
            kind=kind,
            start_line=start + 1,
            end_line=end,
            text="\n".join(lines[start:end]),
        )
        # A fence nested in a prose block (e.g. a snippet inside a list
        # item) is code, not prose: masked out of the ref scan, offsets
        # intact.
        scan_text = (
            block.text
            if kind in ("code", "console")
            else _mask_fenced(block.text, fenced, start, end)
        )
        block.refs = _refs_for(kind, scan_text)
        blocks.append(block)
    return blocks


def _mask_fenced(text: str, fenced: list[tuple[int, int]], start: int, end: int) -> str:
    """Blank fenced/code-block lines that fall inside [start, end)."""
    if not fenced:
        return text
    out = text.split("\n")
    for fence_start, fence_end in fenced:
        if fence_start >= start and fence_end <= end:
            for n in range(fence_start - start, fence_end - start):
                out[n] = " " * len(out[n])
    return "\n".join(out)


def _refs_for(kind: str, text: str) -> list[Ref]:
    if kind == "code":
        return []
    if kind == "console":
        return _console_refs(text)
    return _prose_refs(text)


def _span_body(match: re.Match) -> tuple[str, int]:
    """The backticked span's content and its offset within the block text.

    ``CODE_SPAN_RE`` consumes a run of backticks on each side (``refdes x``
    in double backticks included); both runs are stripped, not one char.
    """
    outer = match.group(0)
    lead = len(outer) - len(outer.lstrip("`"))
    trail = len(outer) - len(outer.rstrip("`"))
    inner = outer[lead : len(outer) - trail]
    body = inner.strip()
    lead_ws = len(inner) - len(inner.lstrip())
    return body, match.start() + lead + lead_ws


def _verbs(tokens: list[str]) -> list[str]:
    verbs: list[str] = []
    for token in tokens[1:]:
        if token.startswith("-"):
            continue  # global flag: skip and keep going
        if _VERB_RE.fullmatch(token):
            verbs.append(token)
            continue
        break
    return verbs


def _command_ref(content: str, raw: str, start: int, context: str) -> Ref | None:
    tokens = content.split()
    if not tokens or tokens[0] != "refdes":
        return None
    command = content.split("#", 1)[0].strip()
    return Ref(
        kind="command",
        raw=raw,
        start=start,
        end=start + len(raw),
        verbs=_verbs(command.split()),
        command=command,
        context=context,
    )


def _prose_refs(text: str) -> list[Ref]:
    refs: list[Ref] = []
    # Code refs live inside code spans, so they are scanned on the raw text;
    # the negatives on such a page (`12:30`, `e.g.:3`) carry no path segment.
    for match in CODE_REF_RE.finditer(text):
        line_start = int(match.group(2))
        refs.append(
            Ref(
                kind="code_ref",
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
                path=match.group(1),
                line_start=line_start,
                line_end=int(match.group(3) or line_start),
                context=text,
            )
        )
    masked = CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), text)
    for match in LINK_RE.finditer(masked):
        target = match.group(2)
        page_part, _, anchor = target.partition("#")
        external = re.match(r"[A-Za-z][\w+.-]*://", target) is not None
        refs.append(
            Ref(
                kind="link",
                raw=text[match.start() : match.end()],
                start=match.start(),
                end=match.end(),
                target=target,
                text=match.group(1),
                page=None if external or not page_part else page_part,
                anchor=None if external or not anchor else anchor,
                external=external,
                context=text,
            )
        )
    for match in CODE_SPAN_RE.finditer(text):
        body, start = _span_body(match)
        command = _command_ref(body, body, start, text)
        if command is not None:
            refs.append(command)
        elif ":" not in body and FILE_PATH_RE.fullmatch(body):
            refs.append(
                Ref(
                    kind="file_ref",
                    raw=body,
                    start=start,
                    end=start + len(body),
                    path=body,
                    context=text,
                )
            )
    refs.sort(key=lambda ref: (ref.start, ref.kind))
    return refs


def _console_refs(text: str) -> list[Ref]:
    refs: list[Ref] = []
    pos = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("$"):
            body = stripped[1:].strip()
            if body.split(" ", 1)[:1] == ["refdes"]:
                start = pos + line.index(stripped)
                command = _command_ref(body, stripped, start, text)
                if command is not None:
                    refs.append(command)
        pos += len(line) + 1
    return refs


def _inside_repo(root_real: str, target: str) -> tuple[bool, str]:
    rel = os.path.relpath(target, root_real)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return False, ""
    return True, rel


def _read_text_file(repo_root: str, path: str):
    """(text, None) for a safe readable text file, (None, error) otherwise.

    Every path is realpath'd against the repo root and checked against
    ``.git/`` *before* any open, and size-capped before any read.
    """
    root_real = os.path.realpath(repo_root)
    if ".." in re.split(r"[\\/]", path):
        # A ref that walks up segments is refused outright: it is the shape
        # of every path-escape probe, and a docs ref has no reason to be
        # written this way (refs are repo-root or page-directory relative).
        return None, "outside repo"
    target = os.path.realpath(os.path.join(root_real, path))
    inside, _rel = _inside_repo(root_real, target)
    if not inside:
        return None, "outside repo"
    tail = target[len(root_real) :]
    if os.sep + ".git" + os.sep in tail or tail == os.sep + ".git":
        return None, "inside .git"
    if not os.path.isfile(target):
        return None, "missing"
    if os.path.getsize(target) > MAX_BYTES:
        return None, "too large"
    with open(target, "rb") as handle:
        head = handle.read(HEAD_BYTES)
        if b"\0" in head:
            return None, "not a text file"
        body = handle.read()
    text = (head + body).decode("utf-8", errors="replace")
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    return lines, None


def _symbols_missing(context: str, file_text: str) -> list[str]:
    """Backticked identifiers in the block that the file never mentions."""
    words: set[str] = set()
    for match in CODE_SPAN_RE.finditer(context):
        body, _ = _span_body(match)
        if "/" in body or body.split(" ", 1)[:1] == ["refdes"]:
            continue  # paths and command lines name files and verbs, not symbols
        words.update(_IDENT_RE.findall(body))
    return sorted(
        word
        for word in words
        if re.search(rf"\b{re.escape(word)}\b", file_text) is None
    )


def _path_card(ref: Ref, repo_root: str) -> dict:
    lines, error = _read_text_file(repo_root, ref.path)
    card: dict = {"kind": ref.kind, "path": ref.path}
    if error == "missing":
        card["exists"] = False
        return card
    if error == "outside repo":
        return {"error": error}
    if error is not None:
        card["exists"] = True
        card["error"] = error
        return card
    card["exists"] = True
    total = len(lines)
    if ref.kind == "file_ref":
        card["lines"] = [
            {"n": n, "text": lines[n - 1]} for n in range(1, min(total, FILE_HEAD_LINES) + 1)
        ]
        return card
    card["cited"] = [ref.line_start, ref.line_end]
    in_range = 1 <= ref.line_start <= total
    card["in_range"] = in_range
    if in_range:
        low = max(1, ref.line_start - WINDOW)
        high = min(total, ref.line_end + WINDOW)
    else:
        low, high = 1, 0
    card["lines"] = [{"n": n, "text": lines[n - 1]} for n in range(low, high + 1)]
    card["symbols_missing"] = _symbols_missing(ref.context, "\n".join(lines))
    return card


def _plain_inline(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # tags strip; alt is an attribute
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*|\*([^*]*)\*", r"\1\2", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    # The site slugifies the rendered HTML text, where < > & arrived as
    # entities, and slugify() maps each punctuation run to one dash.
    return html.escape(text.strip(), quote=False)


def _heading_index(text: str) -> list[dict]:
    """The h2/h3 headings with the ids the docs site gives them.

    Headings come from the parser's own tokens, so fenced content is never
    indexed as a heading (the site anchors rendered ``<h2>``/``<h3>`` only)
    and setext headings land at the level the renderer gives them. All
    heading levels are listed (slugless) because every heading bounds the
    excerpt section of the anchored one.
    """
    front = FRONTMATTER_RE.match(text)
    body = front.group(2) if front else text
    # Headings are numbered against the whole file so excerpts can read the
    # same list of lines the caller passed in.
    offset = text[: len(text) - len(body)].count("\n") if front else 0
    tokens = _build._markdown_parser().parse(body, {})
    seen: dict[str, int] = {}
    headings: list[dict] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        content = tokens[index + 1] if index + 1 < len(tokens) else None
        title = _plain_inline(content.content if content and content.type == "inline" else "")
        entry = {
            "line": token.map[0] + offset,
            "end": token.map[1] + offset,
            "level": int(token.tag[1:]),
            "title": title,
            "slug": "",
        }
        if entry["level"] in (2, 3):
            base = _slugify(title)
            seen[base] = seen.get(base, 0) + 1
            entry["slug"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
        headings.append(entry)
    return headings


def _section_excerpt(lines: list[str], headings: list[dict], index: int) -> list[str]:
    start = headings[index]["end"]  # setext headings span two source lines
    level = headings[index]["level"]
    end = len(lines)
    for later in headings[index + 1 :]:
        if later["level"] <= level:
            end = later["line"]
            break
    body = [line for line in lines[start:end] if line.strip()]
    return body[:EXCERPT_LINES]


def _link_card(ref: Ref, repo_root: str, doc_path: str | None) -> dict:
    if ref.external:
        return {"external": True, "url": ref.target}
    card: dict = {
        "kind": "link",
        "external": False,
        "target": ref.target,
        "page": ref.page,
        "anchor": ref.anchor,
    }
    doc = os.path.abspath(doc_path) if doc_path else os.path.join(
        os.path.realpath(repo_root), ref.page or "index.md"
    )
    if ref.page is not None:
        base = (
            os.path.realpath(repo_root)
            if ref.page.startswith("/")
            else os.path.dirname(doc)
        )
        target = os.path.realpath(os.path.join(base, ref.page.lstrip("/")))
    else:
        target = os.path.realpath(doc)
    inside, _ = _inside_repo(os.path.realpath(repo_root), target)
    if not inside:
        return {"error": "outside repo"}
    card["target_exists"] = os.path.isfile(target)
    # a page link with no anchor asks for the page, and the page exists
    card["anchor_ok"] = ref.anchor is None
    card["heading"] = None
    card["excerpt"] = []
    if not card["target_exists"] or ref.anchor is None:
        return card
    lines, error = _read_text_file(repo_root, os.path.relpath(target, os.path.realpath(repo_root)))
    if error is not None:
        return card
    headings = _heading_index("\n".join(lines))
    for index, heading in enumerate(headings):
        if heading["slug"] == ref.anchor:
            card["anchor_ok"] = True
            card["heading"] = html.unescape(heading["title"])
            card["excerpt"] = _section_excerpt(lines, headings, index)
            return card
    return card


_KNOWN_CACHE: dict[tuple[str, ...], bool] = {}
_HELP_CACHE: dict[tuple[str, tuple[str, ...], tuple[int, int] | None], str] = {}


def clear_caches() -> None:
    """Empty the module-level caches (tests; a server process keeps them warm)."""
    _KNOWN_CACHE.clear()
    _HELP_CACHE.clear()


def _cli_source_signature(repo_root: str) -> tuple[int, int] | None:
    """(mtime_ns, size) of the CLI source, or None when it is not there.

    The help cache keys on this so editing ``src/refdes/cli.py`` invalidates
    the cached ``--help`` cards on its own. A repo without that file (a test
    fixture) gets None, which means: run the help every time, cache nothing.
    """
    try:
        st = os.stat(os.path.join(repo_root, "src", "refdes", "cli.py"))
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _verb_path_is_leaf(verbs: tuple[str, ...]) -> bool:
    """True if refdes's own argparse accepts the verbs and they end at a leaf."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            _refdes_main([*verbs, "--help"])
    except SystemExit as exit_exc:
        if exit_exc.code not in (0, None):
            return False
    usage = out.getvalue().split("\n\n", 1)[0]
    return "{" not in usage  # a group "{a,b,...}" in usage means subcommands


def _help_subprocess(verbs: list[str], repo_root: str) -> tuple[str, bool]:
    """(help text, ok). ok is False on spawn failure, timeout, or exit != 0;
    only an ok run is cacheable, and a failing card is never memoized."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(repo_root, "src")
    env["COLUMNS"] = "100"
    runner = (
        "import sys\n"
        f"sys.path.insert(0, {os.path.join(os.path.realpath(repo_root), 'src')!r})\n"
        "try:\n"
        "    from refdes.cli import main\n"
        "except ModuleNotFoundError:\n"
        f"    sys.path[0:1] = [{REFDES_SRC!r}]\n"
        "    from refdes.cli import main\n"
        "main(sys.argv[1:])\n"
    )
    argv = [sys.executable, "-c", runner, *verbs, "--help"]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
            cwd=repo_root,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", False
    if result.returncode != 0:
        return "", False
    return (result.stdout or "")[:HELP_CHARS], True


def _command_card(ref: Ref, repo_root: str) -> dict:
    card: dict = {"kind": "command", "verbs": list(ref.verbs), "known": False, "help": ""}
    if any(char in METACHARS for char in ref.command):
        return card  # shell-shaped text is never resolved, let alone run
    if not ref.verbs:
        return card
    verbs = tuple(ref.verbs)
    if verbs not in _KNOWN_CACHE:
        _KNOWN_CACHE[verbs] = _verb_path_is_leaf(verbs)
    if not _KNOWN_CACHE[verbs]:
        return card
    card["known"] = True
    # --help spawns a subprocess per command ref (~20 on a page like
    # navis.md, ~12 s per resolve). An edited page re-resolves every ref,
    # so memoize the help per (repo, verb path, CLI source signature):
    # an edit that touches no command costs zero spawns, and editing the
    # CLI source invalidates every entry. Signature None (no cli.py) = no
    # caching at all.
    signature = _cli_source_signature(repo_root)
    key = (os.path.realpath(repo_root), verbs, signature)
    if signature is not None and key in _HELP_CACHE:
        card["help"] = _HELP_CACHE[key]
        return card
    help_text, ok = _help_subprocess(list(verbs), repo_root)
    if ok and signature is not None:
        _HELP_CACHE[key] = help_text
    card["help"] = help_text
    return card


def resolve(ref: Ref, repo_root: str, doc_path: str | None = None) -> dict:
    """One JSON-serialisable card of facts for one ref. Read-only, offline."""
    if ref.kind in ("code_ref", "file_ref"):
        return _path_card(ref, repo_root)
    if ref.kind == "link":
        return _link_card(ref, repo_root, doc_path)
    if ref.kind == "command":
        return _command_card(ref, repo_root)
    return {"error": f"unknown ref kind: {ref.kind!r}"}


def _ref_dict(ref: Ref) -> dict:
    data = dataclasses.asdict(ref)
    data.pop("context")
    return data


def analyze(doc: str, repo_root: str) -> dict:
    text = Path(doc).read_text(encoding="utf-8", errors="replace")
    blocks = []
    for block in parse_doc(text):
        entry = dataclasses.asdict(block)
        entry.pop("refs")
        entry["refs"] = []
        for ref in block.refs:
            item = _ref_dict(ref)
            item["card"] = resolve(ref, repo_root, doc_path=doc)
            entry["refs"].append(item)
        blocks.append(entry)
    return {"doc": Path(doc).as_posix(), "repo": Path(repo_root).as_posix(), "blocks": blocks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refs.py",
        description="Extract and resolve the references a docs page makes "
        "into one JSON object of cards. Read-only, offline.",
    )
    parser.add_argument("doc", help="path to the docs page to analyze")
    parser.add_argument(
        "--repo",
        default=".",
        help="repository root that refs resolve against (default: cwd)",
    )
    args = parser.parse_args(argv)
    if not os.path.isfile(args.doc):
        print(f"refs: no such docs file: {args.doc}", file=sys.stderr)
        return 2
    print(json.dumps(analyze(args.doc, args.repo), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
