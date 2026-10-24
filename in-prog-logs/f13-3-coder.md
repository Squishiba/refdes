# f13-3: editor write-route responses embed the server's absolute paths

Task: 409/422/200 payloads of the editor edit and create routes quoted the
machine project root in free-text fields (`message`, `describe`, diagnostics)
while the sibling `path` field was project-relative. Required: no response
string contains the absolute root; under-root paths become the relative
forward-slash spelling (line suffix rides along), outside-root paths never
stay absolute; one helper at the serialization choke point.

## What was done

- `src/refdes/serve/api.py`: `_write_outcome(app, result)` is the single
  choke point -- `handle()` wraps the POST results of the edit and create
  routes (server.py:829 calls `api.handle`; the tests drive `api.handle`
  thread-free). Service-layer bodies untouched. `_relative_paths` walks
  the whole payload; the text rule is a span scanner (round 4, below):
  under root -> relative forward-slash + line suffix, outside -> bare
  file name (`<outside project>` with no leaf), root -> `.`; a lookbehind
  boundary keeps `http://x/y`, `and/or`, `5/6`; drive roots compare
  case-insensitively; separator runs collapse before comparison (the
  patcher's `json.dumps` quoting doubles Windows backslashes); a
  Windows-shaped root must not go through `os.path.abspath` on Linux.
- Changelog fragment `changelog.d/editor-responses-relative-paths.fixed.md`.
- Verification practice: RED-first test per finding, targeted suites, full
  suite, ruff on touched files (no silencing of unrelated findings).

## Review rounds 1-3 (PR #372, summarized)

Round 1 (windows CI): separator-run collapsing for the `json.dumps`
doubled-backslash spelling; trailing-separator root -> `.`; walk dict
keys and tuple elements (+ json-shape guard). Round 3 (cross-model
review of the round-2 head): two MEDIUMs -- a space-bearing root is
half-scrubbed by a token pass that stops at whitespace, and `file://`
URIs escape the boundary lookbehind; fix: a first pass matching the
KNOWN root literally (all spellings, IGNORECASE drive roots). Addendum
(plugin reviews of the same head): casing pins, outside-root pins,
changelog/log NITs. All verified RED-first, full suite green each round.

## Review round 4 (plugin reviews of the round-3 head): SIMPLIFY

Root cause of all three findings: the first pass swallowed the whole
whitespace-separated run after the root and re-emitted it with separator
runs collapsed. HIGH: a `file://<root>/...` pasted after an under-root
path came back with the ROOT in the 409 `current_text`/`diff` (the
ticket's exact property). MEDIUM: `https://example.com/a//b` lost
slashes; an outside `file:///etc/private/...` kept its directories. LOW:
bare-root boundary missing `! ? :` and including `.`. Reviewer-prescribed
algorithm: consume the root (ONE separator-run pattern) with an optional
`file:/{2,3}` prefix + the separator run after, or the bare root at an
end boundary (letter/digit/`_`/`-` and `.`+letter are NOT boundaries;
the sentence-ending `.` IS) -> `.`; NOTHING after is consumed, so the
continuation is left as written (r2/r3 expectations updated -- a
reviewer-prescribed spec change, not test weakening).

## Review round 4 escalation (deep analysis of the same head): SPAN SCANNER

Probe baseline on this tree (`deep-analysis-pr372-probes.py`): CORE
FAIL 9 (outside-space-quoted/root, json-root-quote/newline/tab,
quoted-child-parentheses/brackets/braces, outside-win-space), EXT FAIL
14, POLICY FAIL 3. Directive: stop adding regex alternatives; replace
the two passes with ONE span scanner; every CORE cell must PASS.

Decisions (fixed, not to be re-litigated): scope = CORE cells (EXT
gaps stay documented: aliases, 8.3 names, dot segments, symlink
realpath); a bare outside token extends over ONE space only when the
next piece is path-shaped; spaces honored inside the exact root and
quoted scalars; regex/switch/POSIX backslash-filenames are POLICY
limits; key collisions get `#2`/`#3`; a sentence-ending root keeps ONE
period.

Scanner (per response, compiled root pattern cached): one left-to-right
scan per string. Precedence: quoted scalar span > `file:` URI prefix >
long-path prefix -> `<outside project>` > drive/absolute span. A span
tries the separator-run root pattern (all spellings ONE pattern,
sentence `.` consumed, `:6`/`:6:2` suffixes, IGNORECASE drive roots);
under-root renders the remainder (windows flavor: forward slashes,
round 6; posix: as-written) with the suffix riding; outside reduces
the token to its leaf. Quoted scalars decode, scrub, re-encode.

Result: probe CORE FAIL = [] (154 PASS; baseline 9 fixed). EXT FAIL 13
= pre-declared; POLICY FAIL = regex, switch only. Bugs found landing:
greedy `file:/{2,3}` ate the root's leading separator; the consumed
sentence period must NOT be re-emitted; suffix/punctuation travel
inside the replacement. Full suite 4618 passed, 2 skipped. (A basetemp
INSIDE the repo -- also via a relative TMPDIR -- breaks
tests/test_scaffold.py + sealing gitignore tests: ignore rules leak
into tmp_path projects; run with the default basetemp and TMPDIR
unset.)

## Round 5 (narrow): file-URI family privacy leak

Five EXT cells left the root verbatim (uri-file:-posix/-drive,
uri-FILE://-posix, uri-file://localhost-*). New rule: scheme `file`
(any casing) + 0-3 slashes + optional `localhost` authority = LOCAL
FILE URI span -- prefix consumed with the path; dotted authority = web
URL, untouched. RED-first (6 cells, probe goldens), fix confined to the
URI branch. Probe: CORE 154/154, EXT FAILs 13 -> 8. Root-literal grep
of ALL probe rows: only root-in-url and root-after-word, POLICY PASS by
design. Full suite 4624 passed, 2 skipped.

## Round 6: windows CI red -- remainder rendered with backslashes

windows-latest run 40054224590 failed 4 tests: under a drive/UNC root
the remainder rendered `items\reqs.yaml` (as-written) where the spec
requires forward slashes. New rule: a Windows-FLAVORED root (drive
letter/UNC in the root string -- flavor derived from the root,
Linux-testable) renders the under-root remainder with forward slashes;
the span ends before an escape tail (separator + no-extension word =
`\n`/`\"` notation); posix keeps backslashes as name characters
(POLICY). RED-first: 13 matrix cells + posix guard RED->green; the 3
round-4 tests pinning as-written outputs updated (spec change,
commented). Probe CORE 154/154, root grep unchanged; full suite 4638
passed, 2 skipped.

## Round 7: space-extension overshoot, windows remainder converts whole

RED-first per item; probe CORE 154/154, zero drift vs r6. (1) The token
space-extension loop advanced by `end + 1 + piece.end()` while
`piece.end()` is absolute -- the run overshot and ate the prose after
the path; a space-crossed token's leaf = the last crossed piece.
(2) Windows remainders convert WHOLE to `/` (`items\sub\NOEXT`); the
span ends only at an escape word; under-root runs cross a space under
the path-shaped-piece rule (4 matrix cells RED->green). Stale docstring
updated; json-shape guard asserts 200 + walks EVERY payload; helpers
imported from the keyless-handle file. Changelog 25 lines. A local
scaffold/seal failure set = tmp_path under in-repo .scratch (basetemp
pollution above), not a regression. Suite 4648 passed, 2 skipped.
## Round 8: an isolated `/` in running text is prose, not a path

HIGH real bug: `_classify`'s fallback treated every boundary-preceded
`/`-initial token as an outside path -- 'value / 2' rendered
'value <outside project> 2'. Decided: an isolated `/` token passes
through; the whole value exactly `/` -> `<outside project>` (probe
outside-root); `/word` stays a path (POLICY). RED-first 6 cells +
guards; round-4 'rooted at / for now' superseded (spec change,
commented). Tidy: dropped the duplicated `read /etc/my config`
assertion, relativeizes -> relativizes (5), docstring says many cells
call private helpers, YAML-escape cells got limit comments; limits
(escaped-space root, `/word`) in changelog (25) + docstring (raw). Probe
CORE 154/154, zero r7 drift; suite 4655 passed, 2 skipped.
