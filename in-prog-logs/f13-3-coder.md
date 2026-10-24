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
  the whole payload; the text rule is a span scanner (round 4): under
  root -> relative forward-slash + line suffix, outside -> bare file name
  (`<outside project>` with no leaf), root -> `.`; a lookbehind boundary
  keeps `http://x/y`, `and/or`, `5/6`; drive roots compare
  case-insensitively; separator runs collapse before comparison (the
  patcher's `json.dumps` quoting doubles Windows backslashes); a
  Windows-shaped root must not go through `os.path.abspath` on Linux.
- Changelog fragment `changelog.d/editor-responses-relative-paths.fixed.md`.
- Verification practice: RED-first test per finding, targeted suites, full
  suite, ruff on touched files (no silencing of unrelated findings).

## Review rounds 1-3 (PR #372, summarized)

Progressive reviews of each head: a space-bearing root was half-scrubbed by
a token pass that stopped at whitespace; `file://` URIs escaped the
boundary lookbehind; the space-crossing run overshot and ate following
prose. Fixed with a first pass matching the KNOWN root literally (all
spellings, IGNORECASE drive roots), casing/outside-root pins, and changelog
/log NITs. All RED-first, full suite green each round.

## Review round 4 (deep analysis): SPAN SCANNER

Directive: stop adding regex alternatives; replace the two passes with ONE
span scanner; every CORE probe cell must pass. Probe baseline on this tree
is `deep-analysis-pr372-probes.py`.

Decisions (fixed, not to be re-litigated): scope = CORE cells (EXT gaps
stay documented: aliases, 8.3 names, dot segments, symlink realpath); a
bare outside token extends over ONE space only when the next piece is
path-shaped; spaces honored inside the exact root and quoted scalars;
regex/switch/POSIX backslash-filenames are POLICY limits; key collisions
get `#2`/`#3`; a sentence-ending root keeps ONE period.

Scanner (per response, compiled root pattern cached): one left-to-right
scan per string. Precedence: quoted scalar span > `file:` URI prefix >
long-path prefix -> `<outside project>` > drive/absolute span. A span
tries the separator-run root pattern (all spellings ONE pattern,
sentence `.` consumed, `:6`/`:6:2` suffixes, IGNORECASE drive roots);
under-root renders the remainder (windows flavor: forward slashes, round 6;
posix: as-written) with the suffix riding; outside reduces the token to its
leaf. Quoted scalars decode, scrub, re-encode. Bugs that landed: greedy
`file:/{2,3}` ate the root's leading separator; the consumed sentence
period must NOT be re-emitted; suffix/punctuation travel inside the
replacement. (A basetemp INSIDE the repo -- also via a relative TMPDIR --
breaks tests/test_scaffold.py + sealing gitignore tests: ignore rules leak
into tmp_path projects; run the full suite with the default basetemp and
TMPDIR unset. The scaffold/seal failures seen locally are this pollution,
not a regression.)

## Rounds 5-8 (each: RED-first, full suite green, probe CORE all pass)

- Round 5 (file-URI family leak): scheme `file` (any casing) + 0-3 slashes
  + optional `localhost` authority = LOCAL FILE URI span, prefix consumed
  with the path; dotted authority = web URL, untouched. Probe goldens
  RED->green; root-literal grep of all probe rows then left only
  root-in-url / root-after-word as POLICY-by-design survivors.
- Round 6 (windows CI red): a Windows-FLAVORED root (drive/UNC, flavor
  derived from the root string so it is Linux-testable) renders the
  under-root remainder with forward slashes; the span ends before an escape
  tail (`\n`/`\"` notation); posix keeps backslashes as name characters
  (POLICY). Round-4 as-written-pinning tests updated as a spec change.
- Round 7: the space-extension loop advanced by `end + 1 + piece.end()`
  with an absolute `piece.end()` -- overshot and ate prose after the path;
  a space-crossed token's leaf is the last crossed piece. Windows
  remainders convert WHOLE to `/` (`items\sub\NOEXT`), crossing a space
  under the path-shaped-piece rule. Stale docstring/json-shape guard tidied.
- Round 8 (real bug): `_classify`'s fallback treated every boundary-preceded
  `/`-initial token as an outside path -- 'value / 2' rendered
  'value <outside project> 2'. An isolated `/` in running text now passes
  through; the whole value exactly `/` -> `<outside project>`; `/word`
  stays a path (POLICY). Round-4 'rooted at / for now' superseded. Tidy:
  dropped a duplicated assertion, relativeizes -> relativizes, docstring
  says many cells call private helpers.

## Round 9 (Jared-decided policy change, on the round-8 head): the root never survives

Removed the two carve-outs (root inside a web URL, root glued to a preceding
word). Rule: an occurrence of the root with a path boundary, PRECEDED by
anything other than start/whitespace/quote/opening punctuation, has its root
text replaced with the marker `<project root>`, every other byte left as
written; sibling-prefix names stay intact (component-boundary rule). So
`https://example.org/<root>/a.md` and `prefix<root>/a.md` both become
`...<project root>/a.md`. The path-span rules now fire only for a span
preceded by start/whitespace/quote/opening punctuation; glued/URL roots
take the marker. RED-first parametrized matrix (URLs http/https/port/query,
glued word, glued `=`, multi-occurrence, windows drive, sibling guards) +
an e2e 409 with a root URL in the file text (asserts the marker survives and
the root literal does not, over the JSON-dumped payload). Probe goldens for
root-in-url/root-after-word flipped to the marker (analysis copy only).
Probe: CORE all pass, ZERO cells now leak a root literal. Changelog/docstring
record the marker rule.

## Round 9 addendum (same push): real bug in `_extend_over_space`

Second defect in the scanner: the docstring said "a single space" but the
loop kept crossing while the next token matched `_PIECE`, so a list of paths
ate the later words and a `:line` suffix was lost:
`see /home/other/plan.md draft.md for details` -> `see draft.md for details`
and `at /home/other/x.md:3 draft.md next` -> `at draft.md next`. Fix: cross
AT MOST ONE space (loop `while` -> `if`) and parse the `:line[:col]` suffix
on the UN-extended token first -- a trailing extension or a `:line` suffix
closes the reference, so `plan.md` / `x.md:3` do not reach across the space.
RED cells for both reproductions plus `a b.md c.md`-style cases; the
existing space-extension cells (round 4/7) stay green. Documented limits
(docstring + changelog): backslashes in a POSIX-rooted remainder are kept as
filename characters; outside the root only the final path segment survives;
UNC roots are NOT case-folded (drive-letter roots are); a root of `/` takes
the root branch before the isolated-slash rule.
