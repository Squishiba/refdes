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
LINK_RE = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
_PATH_SEG = r"(?!-)[\w.+-]+"
CODE_REF_RE = re.compile(
    rf"(?<![\w:/+\-.])({_PATH_SEG}(?:/{_PATH_SEG})+):(\d+)(?:-(\d+))?(?![\w+\-.])"
)
FILE_PATH_RE = re.compile(rf"{_PATH_SEG}(?:/{_PATH_SEG})+")
_VERB_RE = re.compile(r"[a-z][a-z0-9_-]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

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
        block.refs = _refs_for(kind, block.text)
        blocks.append(block)
    return blocks


def _refs_for(kind: str, text: str) -> list[Ref]:
    if kind == "code":
        return []
    if kind == "console":
        return _console_refs(text)
    return _prose_refs(text)


def _span_body(match: re.Match) -> tuple[str, int]:
    """The backticked span's content and its offset within the block text."""
    outer = match.group(0)
    inner = outer[1:-1]
    body = inner.strip()
    lead = len(inner) - len(inner.lstrip())
    return body, match.start() + (len(outer) - len(inner)) // 2 + lead


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
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*|\*([^*]*)\*", r"\1\2", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    # The site slugifies the rendered HTML text, where < > & arrived as
    # entities, and slugify() maps each punctuation run to one dash.
    return html.escape(text.strip(), quote=False)


def _heading_index(text: str) -> list[dict]:
    """The h2/h3 headings with the ids the docs site gives them."""
    front = FRONTMATTER_RE.match(text)
    body = front.group(2) if front else text
    # Headings are numbered against the whole file so excerpts can read the
    # same list of lines the caller passed in.
    offset = text[: len(text) - len(body)].count("\n") if front else 0
    seen: dict[str, int] = {}
    headings: list[dict] = []
    for number, line in enumerate(body.split("\n")):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        title = _plain_inline(match.group(2))
        headings.append(
            {"line": number + offset, "level": level, "title": title, "slug": ""}
        )
        if level in (2, 3):
            base = _slugify(title)
            seen[base] = seen.get(base, 0) + 1
            headings[-1]["slug"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return headings


def _section_excerpt(lines: list[str], headings: list[dict], index: int) -> list[str]:
    start = headings[index]["line"] + 1
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
            card["heading"] = heading["title"]
            card["excerpt"] = _section_excerpt(lines, headings, index)
            return card
    return card


_KNOWN_CACHE: dict[tuple[str, ...], bool] = {}


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


def _help_subprocess(verbs: list[str], repo_root: str) -> str:
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
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "")[:HELP_CHARS]


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
    card["help"] = _help_subprocess(list(verbs), repo_root)
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
