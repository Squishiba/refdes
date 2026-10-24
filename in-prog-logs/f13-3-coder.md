# f13-3: editor write-route responses embed the server's absolute paths

Task: 409/422/200 payloads of the editor edit and create routes quoted the
machine project root in free-text fields (`message`, `describe`, diagnostics)
while the sibling `path` field was project-relative. Required: no response
string may contain the absolute root; under-root paths become the relative
forward-slash spelling (line suffix rides along), outside-root paths must
never stay absolute; one helper at the serialization choke point.

## What was done

- `src/refdes/serve/api.py`: `_write_outcome(app, result)` is the single
  choke point -- `handle()` wraps the POST results of `/api/item/<ref>/edit`
  and `/api/items/create` through it (server.py:829 calls `api.handle`, and
  the tests drive `api.handle` thread-free, so both paths are covered). The
  service-layer bodies are untouched. `_relative_paths` walks the whole
  payload (dict keys/values, list and tuple elements); the text rule is a
  span scanner (round 4, below): under root -> project-relative
  forward-slash spelling with line suffix, outside root -> bare file name
  (`<outside project>` with no leaf), the root itself -> `.`. A lookbehind
  boundary keeps `http://x/y`, `and/or`, `5/6` and relative `path/to/x`
  untouched; drive-letter roots compare case-insensitively; separator runs
  collapse before comparison (the patcher's `json.dumps` quoting doubles
  Windows backslashes in file bytes). On Linux a Windows-shaped root must
  not go through `os.path.abspath` (it prefixes cwd, destroys the drive).
- Changelog fragment `changelog.d/editor-responses-relative-paths.fixed.md`.
- Verification practice all rounds: RED-first test per finding, targeted
  suites, full suite, `ruff check` on touched files (the designer test
  file's RUF059s are fixed in round 4; no silencing of unrelated findings).

## Review rounds 1-3 (PR #372, summarized)

Round 1 (windows CI): separator-run collapsing for the `json.dumps`
doubled-backslash spelling; trailing-separator root -> `.`; walk dict keys
and tuple elements (+ json-shape guard test). Round 3 (cross-model review
of caa2142): two MEDIUMs -- a space-bearing root is half-scrubbed by a
token pass that stops at whitespace, and `file://` URIs escape the
boundary lookbehind; reviewer-prescribed fix: a first pass matching the
KNOWN root literally (native/forward/JSON-escaped/`file://` spellings,
IGNORECASE for drive roots). Addendum (plugin reviews of caa2142): casing
pins, outside-root pins, changelog/log NITs. All verified RED-first, full
suite green each round.

## Review round 4 (plugin reviews of 5cf61a2): SIMPLIFY

Root cause of all three findings: the first pass swallowed the whole
whitespace-separated run after the root and re-emitted it with separator
runs collapsed. HIGH: a `file://<root>/...` pasted after an under-root
path came back with the ROOT in the 409 `current_text`/`diff` (the
ticket's exact property). MEDIUM: `https://example.com/a//b` lost
slashes; an outside `file:///etc/private/...` kept its directories. LOW:
bare-root boundary missing `! ? :` and including `.`. Reviewer-prescribed
algorithm: the first pass consumes the root (ONE separator-run pattern)
with an optional `file:/{2,3}` prefix plus the separator run that
follows, or the bare root at an end boundary (letter/digit/`_`/`-` and
`.`+letter are NOT boundaries; the sentence-ending `.` IS) -> `.`;
NOTHING after is consumed. Consequence pinned in tests: the continuation
is left as written (r2/r3 expectations updated -- a reviewer-prescribed
spec change, not test weakening). Chunk-2: `assert_no_root` on both
front-matter saves (clears 2 RUF059), docstring truthfulness, a renamed
test, wrapped lines, `_root` unpack; helper docstring states the
outside-path-with-spaces outcome.

## Review round 4 escalation (deep analysis of 5cf61a2): SPAN SCANNER

Probe baseline on this tree (`deep-analysis-pr372-probes.py`, saved in
`.scratch/probes-r4-baseline.jsonl`): CORE FAIL 9 (outside-space-quoted,
outside-space-root, json-root-quote/newline/tab, quoted-child-parentheses/
brackets/braces, outside-win-space), EXT FAIL 14, POLICY FAIL 3. Directive:
stop adding regex alternatives; replace the two passes with ONE span
scanner; every CORE cell must PASS.

Decisions (fixed, not to be re-litigated): scope = CORE cells (EXT cells
stay documented gaps: `%20`/long-path aliases, 8.3 names, dot segments,
symlink realpath -- no filesystem access); a bare outside token extends
over ONE space only when the next piece is path-shaped; spaces fully
honored inside the exact root and quoted scalars; regex/switch/POSIX-
backslash-filename stay POLICY limits (no intent detector); dict-key
collisions get `#2`/`#3`; a sentence-ending root keeps ONE period.

Scanner (per response, compiled root pattern cached): one left-to-right
scan per string. Precedence: quoted scalar span > `file:` URI prefix >
long-path prefix (`\\?\`, `//?/` -> `<outside project>`) > drive/absolute
span. A span tries the separator-run root pattern (native/forward/JSON-
doubled as ONE pattern, sentence `.` consumed, `:6`/`:6:2` suffixes,
IGNORECASE drive roots) anchored at its start; under-root renders the
remainder (windows flavor: forward slashes, round 6; posix: as-written)
with the suffix riding; outside reduces the whole token (plus
path-shaped space-joined pieces) to its leaf. Quoted scalars decode
(JSON, YAML-fallback incl. `\xHH`), scrub, re-encode; replacements are
never re-scanned.

Result: probe CORE FAIL = [] (154 PASS; baseline 9 fixed). EXT FAIL 13
= pre-declared list; json-unicode-root flipped to PASS. POLICY FAIL =
regex, switch only. Bugs found while landing: greedy `file:/{2,3}` ate
the root's leading separator; the consumed sentence period must NOT be
re-emitted; suffix/punctuation travel inside the replacement. Full suite
4618 passed, 2 skipped. (A basetemp INSIDE the repo breaks
tests/test_scaffold.py + sealing gitignore tests -- git ignore rules
leak into tmp_path projects; use the default basetemp.)

## Round 5 (narrow): file-URI family privacy leak

Five EXT cells left the root verbatim (uri-file:-posix/-drive,
uri-FILE://-posix, uri-file://localhost-posix/-drive). New rule: scheme
`file` (any casing) + 0-3 slashes + optional `localhost` authority =
LOCAL FILE URI span -- prefix consumed with the path; dotted authority =
web URL, untouched. RED-first (6 cells, all probe goldens), fix confined
to the scan loop's URI branch. Probe: CORE 154/154, EXT FAILs 13 -> 8
(all pre-declared: dotdot x3, encoded-uri, unc-case, long x2,
short-name). Root-literal grep of ALL probe rows: only root-in-url and
root-after-word, POLICY PASS by design. Full suite 4624 passed, 2
skipped.

## Round 6: windows CI red -- remainder rendered with backslashes

windows-latest run 40054224590 failed 4 tests: under a drive/UNC root
the remainder rendered `items\reqs.yaml` (as-written) where the spec
requires the `path` field's forward-slash spelling. New rule: a
Windows-FLAVORED root (drive letter/UNC in the root string -- flavor
derived from the root, an explicit renderer parameter, Linux-testable)
renders the under-root remainder with forward slashes; the span ends
before an escape tail (separator + no-extension word = `\n`/`\"`
notation, not a separator); posix keeps backslashes as name characters
(POLICY). RED-first: 13 matrix cells (the 4 CI failures as Linux shapes)
+ posix guard all RED->green; the 3 round-4 tests that pinned
as-written outputs updated to the rule (spec change, commented). Probe
CORE 154/154, root grep unchanged; full suite 4639 passed, 2 skipped.
