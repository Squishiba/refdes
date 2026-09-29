# VS Code adapter: the false README claim, and the ten §7.1 contract tests

Two parts, as briefed. Log written as I went.

## Part 1 — `editors/vscode/README.md` claimed no test coverage at all

**The false claim, verbatim, at the old `editors/vscode/README.md:172-175`:**

> There is no automated or headless test coverage for this extension, so checking
> the features above means exercising them in a real VS Code instance; reading
> `extension.js` can show the pieces are wired together, but it is not the same
> as having watched them work.

**How it got there, and why the original check missed it.** The prior task's
evidence was `find editors/vscode -iname "*test*"` (empty), and
`editors/vscode/package.json` having no `scripts` and no `devDependencies`
(also empty). Both are true. Neither is the question that mattered: this repo's
extension tests live in the *top-level* `tests/` directory, not under
`editors/vscode/`, and they are Python, not JavaScript. Nothing was wrong with
the JS side; the search was scoped to the wrong tree.

**What actually exists.** `tests/test_vscode_extension.py`, 5 tests, read in
full. They pin:

1. `test_extension_activates_on_current_project_marker` — §7.2's named
   activation regression (PR #58): `package.json`'s `activationEvents` and
   `extension.js`'s `findRoot` both name `refdes-project.yaml`, neither names
   the retired `refdes.yaml` (matched with a negative-lookbehind regex, because
   `refdes.yaml` *is* a substring of `refdes-project.yaml`).
2. `test_hover_still_renders_the_index_body_and_adds_the_snapshot_facts` —
   Slice V0: `itemMarkdown(item, view)` still exists, the hover provider still
   hands it the item view, and `coverage`/`check`/`diagnostics` are returned by
   `_item_view` in `src/refdes/serve/api.py` *and* read off the view by the
   extension.
3. `test_serve_client_and_the_cli_agree_on_the_launch_line` — the two sides of
   one literal: `src/refdes/cli.py` prints `refdes serve: {app.launch_url}` and
   `editors/vscode/serveClient.js` declares `LAUNCH_PREFIX = "refdes serve: "`.
4. `test_the_token_travels_only_in_the_header_the_server_checks` — the header
   name is read out of `serve/security.py`'s `TOKEN_HEADER`, and the client
   sends that header, passes no `--token`, spawns `<cmd> <args> serve --no-open`,
   dials `127.0.0.1` and never `localhost`.
5. `test_no_direct_item_file_writes_in_extension_source` — §4/§6 Q5's ban on a
   second write path: no `applyEdit`/`WorkspaceEdit`/`fs.writeFile` family in
   `editors/vscode/*.js` (comment lines skipped, so prose that *names* the ban
   does not fail the test that enforces it).

**CI runs them.** `pyproject.toml:84-85`:

```
[tool.pytest.ini_options]
testpaths = ["tests"]
```

so `tests/test_vscode_extension.py` is collected by a bare `pytest`, and
`.github/workflows/tests.yml` runs the suite on every push and PR.

**The real gap** is what §7.2 of the design doc says, not "no tests". Its closing
paragraph: "A full `@vscode/test-electron` harness (real extension host, real
webview) is deferred to whatever slice first ships a webview, and is explicitly
*not* a prerequisite for the read-only slice." So the true statement is: the
existing coverage is real but **static** — it reads the extension's source as
text and cross-checks it against the Python server's source — and there is no
**live extension-host** harness that runs the extension inside VS Code. The
README now says exactly that, in place of the false claim, rather than deleting
the note.

## Part 2 — `tests/test_vscode_adapter_contract.py`, the ten §7.1 tests

**None of the ten already existed.** `grep -rn "<name>" tests/ docs/ src/`
for each name: every hit is the design doc's own bullet at
`docs/design/editor-vscode-adapter.md:520-553`. No implementation anywhere,
under any other filename.

The ten, transcribed from §7.1 and implemented in that order:

| # | test | what it does |
|---|---|---|
| 1 | `test_serve_prints_launch_url_as_first_stdout_line` | real `python -m refdes.cli … serve --no-open` subprocess; first stdout line full-matches `refdes serve: http://127.0.0.1:<port>/?token=<t>`; parsed token → `GET /api/revision` = 200 |
| 2 | `test_launch_url_token_never_appears_in_argv` | the live child's own command line holds neither the token nor any `token=`; plus the reason it cannot: `serve`'s argparse subparser declares no token option |
| 3 | `test_token_gates_reads_as_well_as_writes` | `GET /api/items` with no `X-Refdes-Token` = 403 and no item data; with it = 200 |
| 4 | `test_mutation_without_origin_is_refused` | `Origin`-less POST to `/api/item/DEC-001/edit` = 403, and the *same* payload with a matching Origin = 200 (so the 403 is the gate, not a bad body) |
| 5 | `test_mutation_origin_must_match_host` | `Origin: http://localhost:<p>` against `Host: 127.0.0.1:<p>` = 403; the same Origin against `Host: localhost:<p>` is accepted |
| 6 | `test_item_view_reports_edit_state_for_every_field` | every entry in `edit.fields` carries `editable`, and a non-empty `reason` whenever it is false; on a sealed log and an imported item every field is false with the blocked reason |
| 7 | `test_conflict_payload_carries_current_text_and_diff` | edit the file behind a held `file_revision`, POST → 409 carrying non-empty `current_text` and a `diff` naming the change; file byte-identical afterwards |
| 8 | `test_no_write_server_refuses_every_mutation_route` | under `read_only=True` all three mutation routes are 403 (`/api/item/<ref>/edit`, `/api/items/create`, `/api/assets`) and the tree does not move a byte |
| 9 | `test_editor_csp_refuses_framing` | through the launch-URL cookie flow, `GET /edit/` carries `frame-ancestors 'none'` |
| 10 | `test_deep_link_shape_matches_server_toolbar` | the `/edit/#/items/<key>` the preview toolbar injects, resolved through the server, is byte-identical to the URL `ServeClient.deepLink` builds for the same key |

**Fixture.** Modelled on `tests/test_serve_editor_e2e.py`: `serve_support`'s
`SERVE_SCHEMA` and item files, plus an `imports:` block and an upstream
`items.json` so an *imported* (external) item exists, keyed by an ordinary
writable run, and sealed with `build(project, seal_write=True)` exactly as e2e
does. The `EditorApp` fixture is the `served` shape from e2e/security
(`EditorApp(config, poll_interval=60)`, `Client(app)`, stopped in `finally`).

**One wording drift found, and it is in the doc, not the server.** §7.1's test 6
says "on a sealed log and an imported item, every field is false with the same
reason". In `serve/api.py:edit_state` the `id`, `key` and `type` pseudo-fields
are hard-coded non-editable with the *identity* reason ("identity: id, key and
type are not editable in v1") *before* the sealed/imported gate is consulted, so
on a sealed log the item's own field (`summary`) carries the sealed reason while
`id`/`key`/`type` carry the identity reason. Everything the promise is actually
about holds: every field is false, nothing is false without a stated reason, and
every field of the *item* is false with the same blocked reason. The test asserts
that reading — full strength, and it also asserts the identity fields are false
with a non-empty reason of their own, so nothing is left unexplained. I did not
touch the server and I did not weaken the doc's claim into a different one; the
distinction is recorded here and in a comment in the test.

**Everything else matched.** No header name had drifted (`X-Refdes-Token` is
what `security.TOKEN_HEADER` holds and what the client sends), no status code
had drifted (403 for the Origin and read-only gates, 409 for the conflict, 200
for the item view), and the deep link shapes on both sides are the same string.

## Part 1 — the README diff

Before (`editors/vscode/README.md:172-175`, the "Developing" section):

```
There is no automated or headless test coverage for this extension, so checking
the features above means exercising them in a real VS Code instance; reading
`extension.js` can show the pieces are wired together, but it is not the same
as having watched them work.
```

After:

```
There is automated coverage, but it is static rather than live.
`tests/test_vscode_extension.py` runs with the project's test suite and checks
this extension's source as text against the server it talks to: the activation
marker, the `refdes serve:` launch line, the `X-Refdes-Token` header, the
item-view facts the hover renders, and the ban on writing an item file from
here. `tests/test_vscode_adapter_contract.py` pins the server side of that same
contract, driving a real `refdes serve` over real sockets.

What that does not do is run the extension inside VS Code: there is no
`@vscode/test-electron` harness, so checking the features above still means
exercising them in a real instance. Reading the source can show the pieces are
wired together, but it is not the same as having watched them work.
```

Not deleted — replaced. The false claim is gone and the true, narrower one (no
*live extension host*) is stated in its place, which is what §7.2's closing
paragraph actually says.

## Verification

### 1. The ten new tests plus the five existing ones

```
$ pytest tests/test_vscode_extension.py tests/test_vscode_adapter_contract.py -v
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.1.1, pluggy-1.6.0 -- /home/jorb/work/venv-refdes/bin/python
cachedir: .pytest_cache
rootdir: /home/jorb/.paseo/worktrees/16msma8v/frail-crocodile
configfile: pyproject.toml
collecting ... collected 15 items

tests/test_vscode_extension.py::test_extension_activates_on_current_project_marker PASSED [  6%]
tests/test_vscode_extension.py::test_hover_still_renders_the_index_body_and_adds_the_snapshot_facts PASSED [ 13%]
tests/test_vscode_extension.py::test_serve_client_and_the_cli_agree_on_the_launch_line PASSED [ 20%]
tests/test_vscode_extension.py::test_the_token_travels_only_in_the_header_the_server_checks PASSED [ 26%]
tests/test_vscode_extension.py::test_no_direct_item_file_writes_in_extension_source PASSED [ 33%]
tests/test_vscode_adapter_contract.py::test_serve_prints_launch_url_as_first_stdout_line PASSED [ 40%]
tests/test_vscode_adapter_contract.py::test_launch_url_token_never_appears_in_argv PASSED [ 46%]
tests/test_vscode_adapter_contract.py::test_token_gates_reads_as_well_as_writes PASSED [ 53%]
tests/test_vscode_adapter_contract.py::test_mutation_without_origin_is_refused PASSED [ 60%]
tests/test_vscode_adapter_contract.py::test_mutation_origin_must_match_host PASSED [ 66%]
tests/test_vscode_adapter_contract.py::test_item_view_reports_edit_state_for_every_field PASSED [ 73%]
tests/test_vscode_adapter_contract.py::test_conflict_payload_carries_current_text_and_diff PASSED [ 80%]
tests/test_vscode_adapter_contract.py::test_no_write_server_refuses_every_mutation_route PASSED [ 86%]
tests/test_vscode_adapter_contract.py::test_editor_csp_refuses_framing PASSED [ 93%]
tests/test_vscode_adapter_contract.py::test_deep_link_shape_matches_server_toolbar PASSED [100%]

============================== 15 passed in 4.04s ==============================
```

The new file is stable: run three more times back to back, 10 passed each time
(the two subprocess tests included).

### 2. The full suite

```
$ pytest tests/ -q
2779 passed, 2 skipped in 197.45s (0:03:17)
```

The 2 skips are pre-existing and not from this file (the new module reports
`10 passed`, no skips).

### 3. Ruff, scoped

```
$ ruff check tests/test_vscode_adapter_contract.py --select I,F
All checks passed!
```

(`E501` was checked too while the file was being written — clean, under the
repo's `line-length = 100`.)

### 4. Evidence the subprocess tests read a real process

Scratch probe (`.scratch/probe_launch_line.py`, left in place per AGENTS.md):

```
FIRST LINE REPR: 'refdes serve: http://127.0.0.1:56073/?token=m76rkwKEU4n0nOVvPZOXcOW2RG9W5jnNTsOCQXmjGls\n'
MATCHES: True
CMDLINE: /home/jorb/work/venv-refdes/bin/python -m refdes.cli -c /tmp/tmp36fazksk/refdes-project.yaml serve --no-open
serve --token exit: 2 | refdes: error: unrecognized arguments: --token=abc
```

Three things confirmed at runtime rather than from source: the first stdout line
full-matches the shape; the live `/proc/<pid>/cmdline` holds the argv the
extension builds and no token; and `refdes serve` has no `--token` option at
all, which is *why* argv cannot carry one.

## What I did not do

- No server source and no `editors/vscode/*.js` change. Everything here pins
  behaviour that already exists; the one place the design doc's wording was
  looser than the server (the identity pseudo-fields on a blocked item, above) is
  recorded rather than "fixed" in the server.
- `tests/test_vscode_extension.py` untouched.
- No `git stash`; nothing outside this worktree written; temporary probe files
  left in `.scratch/`.

## One judgement call worth naming

`changelog.d/vscode-adapter-test-coverage-note.fixed.md` — the fragment the F7
task added, still pending, unreleased — states the false claim outright ("The
extension has no automated or headless test coverage -- no `scripts` or
`devDependencies` in its `package.json`, no test file anywhere under
`editors/vscode/`..."). `release.py` folds pending fragments into `[Unreleased]`,
so shipping both would put the false statement and its correction in the same
release. I deleted the stale fragment and let
`changelog.d/vscode-readme-test-coverage-claim.fixed.md` carry the corrected
statement. Nothing released said otherwise, so no history is rewritten.

## Finished?

Yes — all ten §7.1 tests implemented and passing, Part 1's README note corrected,
full suite green, ruff clean on the new file, two changelog fragments added.

