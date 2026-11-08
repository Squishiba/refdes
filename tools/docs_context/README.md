# `tools/docs_context` — the docs-context viewer (maintainer notes)

A local, read-only web viewer for **one** docs page, meant to sit open
beside the editor while you edit it. The left column lists the page's
blocks; the right shows a card per reference the selected block makes —
`code_ref` (e.g. `src/refdes/cli.py:3227`), `file_ref`, `command` (a
backticked `refdes …` line), `link` — each resolved into facts read
from the repository, flagged when stale: file not found, cited line
past the file end, a symbol the cited file never mentions, unknown
command, broken anchor. `tools/` is not shipped; `refs.py` imports
`refdes.build`/`refdes.cli`, so run from a checkout with the project
dependencies installed (the dev venv works); claims here were checked
against the sources and live probes on 2026-11-07.

## Starting it

From the repo root (`--help` output, run 2026-11-07):

```
$ python tools/docs_context/server.py --help
usage: server.py [-h] [--repo REPO] [--port PORT] [--no-open]
                 [--llm-url LLM_URL] [--llm-model LLM_MODEL]
                 doc

Serve a read-only web viewer for the references one docs page makes. Loopback
only, GET only, writes nothing.

positional arguments:
  doc                   path to the docs page to serve

options:
  -h, --help            show this help message and exit
  --repo REPO           repository root refs resolve against (default: found
                        upward from the doc, else the doc's parent)
  --port PORT           port to bind (default: ephemeral)
  --no-open             do not open a browser on startup
  --llm-url LLM_URL     OpenAI-compatible base url for the ask buttons
                        (default: http://127.0.0.1:8080/v1; loopback only --
                        127.0.0.1, localhost, or ::1)
  --llm-model LLM_MODEL
                        model id to ask (default: discovered from the llm's
                        /models)
```

`python tools/docs_context/server.py docs/index.md --no-open --port 0`
binds 127.0.0.1 on an ephemeral port and prints the URL as the only
stdout line (observed: `docs-context: http://127.0.0.1:33193/`); the
per-request log goes to stderr. `--repo` defaults to the first parent
of the doc containing `.git` (dir *or* file, so worktrees work) or
`refdes-project.yaml`; docs outside the repo, missing/non-`.md` docs
and a non-loopback `--llm-url` each exit 2 on stderr. The page polls
the mtime every 1500 ms and re-renders in place after an edit.
`refs.py` is also a CLI: `python tools/docs_context/refs.py
docs/index.md --repo .` prints the same analysis as JSON, no server.

## Endpoints

| route | what it does |
| --- | --- |
| `GET /`, `GET /static/<name>` | the viewer page and `app.js`/`style.css` (strict name regex) |
| `GET /api/doc[?path=…]` | the block/ref/card JSON, cached per file by (mtime_ns, size); `path` must be a repo-relative `.md` inside the repo (400 on escapes, 404 missing) |
| `GET /api/mtime` | `{"mtime": …}` — a stat call only, never a parse |
| `GET /api/file?path=&line=` | ±15 lines around `line` of one repo file, through `refs.py`'s path guard |
| `GET /api/focus` | the remembered focus `{seq, line, block, path}`; `{0, null, null, <served doc>}` before any POST; reads memory only, never parses |
| `POST /api/focus` | `{"path": …, "line": …}` — see "Following the editor" |
| `POST /api/ask` | `{"block": …, "ref": …, "question": …}` — see "Ask" |

Guards, verified live on 2026-11-07 with curl against a running
instance: every request passes a Host check first — host must be
`127.0.0.1`, `localhost` or `::1` on the server's own port, else 403
`bad host`. `PUT` (and DELETE/PATCH/OPTIONS and any other method word)
is 405 JSON, as is `GET /api/ask`. Every response carries `nosniff`
and `no-store`; no CORS headers. Both POST routes share
(`server.py::_json_post`): `X-Docs-Context: 1` required (403 without
it), an `Origin` header must name the server's own origin (403),
`Content-Type: application/json` required (415), body caps 4096 for
`/api/ask` / 1024 for `/api/focus` (over-cap: drained, then 400),
chunked bodies refused (400).

## Following the editor (DC-4a)

`POST /api/focus {"path": …, "line": …}`: when `path` names the served
doc (posix, case-sensitive, leading `./` normalised — **by string
comparison alone; the path is never opened**), the server resolves the
line to its block from its own cached analysis and remembers it **in
memory only** (lock-protected `seq`, incrementing on every accepted
POST; nothing written to disk), answering `{"followed": true, "line":
N, "block": B}`. Any other path answers `{"followed": false, "reason":
"other-doc"}`, changing nothing. Verified live: line 12 → block 11.

The page polls `GET /api/focus` on the same 1500 ms tick as the mtime
poll: with the header "follow the editor" checkbox (checked by
default) on, a focus whose `seq` moved selects the block and scrolls it
into view; **a manual click wins until the next accepted focus** (the
page de-dupes by block). `j`/`k` and the arrows move by block.

## Ask (DC-3)

Each card has three buttons — `explain`, `misread`, `match`. The POST
body carries only `{block, ref, question}`; the prompt is built
server-side by `llm.build_messages` from the server's own current
analysis (block text, the ref, the card's facts) plus one of the three
fixed instructions, so the browser can never supply prompt text; the
system prompt pins the model to a reading aid that never drafts prose.
Answers render via `textContent`, labelled advisory. One request at a
time (409 busy); LLM failures are 502/504 with the `LlmError` kind.

`llm.py` needs an OpenAI-compatible endpoint, configured by two flags
and nothing else: `--llm-url` (default `http://127.0.0.1:8080/v1`,
**must be loopback** — only the literal name `localhost` or a loopback
ip literal, checked before any socket; redirects are refused, so the
prompt never leaves the machine; no api-key option) and `--llm-model`
(omit it and the first id from `GET {base}/models` is used), with
`temperature 0`, `max_tokens 700`, 120 s timeout. Live on 2026-11-07
this box's endpoint at the default url answered the ask route: 200,
model `flash-next`.

## Safety stance

Read-only: the server writes nothing (tests snapshot the repo tree
around a full route sweep); a posted focus path is never opened.
Referenced paths are realpath-checked inside the repo and against
`.git/` *before* any `open()` (tests prove it with `open` monkeypatched
to raise); external links are plain text, never fetched. Command cards
spawn only verb paths `refdes.cli`'s argparse accepts, as list argv
with `--help` appended — never a shell, and shell metacharacters are
gated out first. Loopback bind, Host allowlist, DOM text via
`textContent` only.

## Not built yet

- **DC-4b, the VS Code extension that posts the cursor, is planned and
  not present.** Nothing in this repo POSTs to `/api/focus` (a grep
  for `api/focus` names only the viewer, its tests, and logs), so the
  viewer follows whatever local client posts — today that is curl.

## Running its tests

From the repo root, with the dev venv (`.[dev,xlsx]`):

```
PYTHONPATH=$PWD/src python -m pytest -q -n 4 --dist worksteal \
    tests/test_docs_context_refs.py tests/test_docs_context_server.py \
    tests/test_docs_context_ask.py tests/test_docs_context_focus.py
```

Run 2026-11-07: `175 passed` in ~18 s (adding
`tests/test_crossplatform_lint.py` → `201 passed`); tests import the
modules off `tools/` by path, like `tests/test_pr_size.py`.
