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
  service-layer bodies are untouched.
- `_relative_paths` walks the whole payload (dict keys/values, list and
  tuple elements); `_relative_paths_in_text` is a two-pass text rule:
  a literal first pass for the KNOWN root (rounds 3-4, below), then a
  token pass: under root -> project-relative forward-slash spelling with
  line suffix, outside root -> bare file name (`<outside project>` with no
  leaf), the root itself -> `.`. A lookbehind boundary keeps `http://x/y`,
  `and/or`, `5/6` and relative `path/to/x` untouched; drive-letter roots
  compare case-insensitively; separator runs collapse before comparison
  (the patcher's `json.dumps` quoting doubles Windows backslashes in file
  bytes -- the round-1 windows-latest CI failure).
  On Linux a Windows-shaped root must not go through `os.path.abspath`
  (it prefixes cwd and destroys the drive spelling).
- Changelog fragment `changelog.d/editor-responses-relative-paths.fixed.md`.
- Verification practice all rounds: RED-first test per finding, targeted
  suites, full suite, `ruff check` on touched files (the designer test
  file's RUF059s are fixed in round 4; no silencing of unrelated findings).

## Review rounds 1-3 (PR #372, summarized)

Round 1 (windows CI): separator-run collapsing for the `json.dumps`
doubled-backslash spelling; trailing-separator root -> `.`; walk dict keys
and tuple elements (+ json-shape guard test).
Round 3 (cross-model review of caa2142): two MEDIUMs -- a space-bearing
root is half-scrubbed by a token pass that stops at whitespace, and
`file://` URIs escape the boundary lookbehind. Reviewer-prescribed design:
a first pass matching the KNOWN root literally (spellings: native,
forward-slash, JSON-escaped doubling, `file://`/`file:///` prefixes,
IGNORECASE for drive roots), swallowing the separator after the root;
token pass keeps outside-root -> basename and gains a `file:` branch.
Addendum (plugin reviews of caa2142): casing pins, outside-root pins,
changelog/log NITs. All verified RED-first, full suite green each round.

## Review round 4 (plugin reviews of 5cf61a2): SIMPLIFY

Root cause of all three findings: the first pass swallowed the whole
whitespace-separated run after the root and re-emitted it with separator
runs collapsed. HIGH: a `file://<root>/...` pasted after an under-root
path came back `file:/tmp/.../secret/x.md:4` -- the ROOT in the 409
`current_text`/`diff` (reachable through file text; the ticket's exact
property). MEDIUM: `https://example.com/a//b` lost slashes; an outside
`file:///etc/private/...` kept its directories. LOW: bare-root boundary
missing `! ? :` (spaced root before them leaked its tail) and including
`.` (`proj.old` sibling -> `..old`, sentence-ending root -> `..`).

Reviewer-prescribed algorithm, followed: the first pass consumes the root
(as ONE separator-run pattern -- native/forward/JSON-doubled spellings
collapse into `[\\/]+` joins) with an optional `file:/{2,3}` prefix, plus
the separator run that follows (-> ``), or the bare root at an end
boundary (letter/digit/`_`/`-` and `.`+letter are NOT boundaries; the
sentence-ending `.` IS consumed) -> `.`. NOTHING after is consumed; the
token pass keeps its full job. Net code shrank: `_PATH_SEG`,
`_NOT_ABS_START`, `_ROOT_END`, the spelling set and the cont group are
gone. Consequence pinned in tests: the continuation is left as written
(escaped text stays escaped -- r2/r3 expectations updated to
`items\reqs.yaml`-style outputs; a spec change prescribed by the reviewer,
not a test weakening).

RED-first: 3 tests (HIGH end-to-end 409 with a pasted `file://` URI,
MEDIUM text-unchanged pair, LOW punctuation-boundary set) -- all 3 RED on
`5cf61a2`, all green after. Chunk-2 test findings F1-F5: `assert_no_root`
added to both front-matter saves (clears 2 RUF059; the full-payload walk
now covers the ticket's headline md shape), json-shape guard docstring
truthfulness (the `walk()` is the tuple proof, not the discarded
round-trip), the "posix root" test renamed to what it feeds
(Windows-shaped, doubled continuation), five 101-111-char lines wrapped,
`_root` for the unused unpack. Helper docstring now states the
outside-path-with-spaces outcome (the ticket's documented limit).
Changelog's "non-path text pass through unchanged" is now true, and says
why.

## Review round 4 escalation (deep analysis of 5cf61a2): SPAN SCANNER

Probe baseline on this tree (`deep-analysis-pr372-probes.py`, saved in
`.scratch/probes-r4-baseline.jsonl`): CORE FAIL 9 (outside-space-quoted,
outside-space-root, json-root-quote/newline/tab, quoted-child-parentheses/
brackets/braces, outside-win-space), EXT FAIL 14, POLICY FAIL 3. Directive:
stop adding regex alternatives; replace the two passes with ONE span
scanner; every CORE cell must PASS.

Decisions (fixed, not to be re-litigated): scope = CORE cells (EXT cells
stay documented gaps: `file:/` single-slash, `FILE://` on posix roots,
`file://localhost` authority, `%20`/long-path aliases, 8.3 names, symlink
realpath -- no filesystem access at all); a bare outside token extends
over ONE space only when the next piece is unambiguously path-shaped
(contains a separator, no colon, ends in a file extension), spaces are
fully honored inside the exact known root and inside quoted scalars;
regex/switch/POSIX-backslash-filename stay POLICY documented limits (no
intent detector); dict-key collisions get `#2`/`#3` suffixes (no data
lost); a sentence-ending root keeps ONE period; lexical-only, no Windows
filesystem claims.

Scanner (per response, compiled root pattern cached): one left-to-right
scan per string. Precedence at each position: quoted scalar span
(`"`-delimited, escapes honored) > `file:` URI prefix > long-path prefix
(`\\?\`, `//?/` -> `<outside project>`, no alias matching) > drive/
absolute span. A span is classified by trying the separator-run root
pattern (native/forward/JSON-doubled spellings as ONE pattern, sentence
`.` consumed, bare-root `:6`/`:6:2` suffixes, IGNORECASE for drive roots)
anchored at its start; under-root renders the remainder AS-WRITTEN with
the suffix riding; outside reduces the whole token (plus path-shaped
space-joined pieces) to its leaf, `<outside project>` with none. Quoted
scalars decode (JSON, YAML-fallback incl. `\xHH`), scrub, re-encode;
unchanged content re-emits the original bytes. Replacements are never
re-scanned (fixes quoted-child-* and the HIGH URI case).

Result: probe CORE FAIL = [] (154 PASS; baseline 9 FAILs all fixed:
outside-space-quoted/-root, json-root-quote/newline/tab,
quoted-child-parentheses/brackets/braces, outside-win-space). EXT FAIL 13
= the pre-declared out-of-scope list; json-unicode-root flipped to PASS
as a freebie of the JSON decode. POLICY FAIL = regex, switch only
(documented grammar, decision 3); key-collision and posix-backslash-name
PASS. Bugs found while landing: the greedy `file:/{2,3}` prefix ate the
slash the root's leading separator run needs; the consumed sentence
period must NOT be re-emitted (the `.` replacement is the dot);
suffix/punctuation travel inside the replacement, never back into the
scan. Full suite 4618 passed, 2 skipped. (A basetemp INSIDE the repo
breaks tests/test_scaffold.py + sealing gitignore tests -- git's
ignore/rev-parse rules leak into tmp_path projects; run the suite with
the default basetemp.)

## Round 5 (narrow): file-URI family privacy leak

Five EXT cells left the root verbatim (uri-file:-posix/-drive,
uri-FILE://-posix, uri-file://localhost-posix/-drive). New rule:
scheme `file` (any casing) + 0-3 slashes + optional `localhost`
authority = LOCAL FILE URI span -- prefix consumed with the path; a
dotted authority is a web URL, untouched. RED-first (6 cells, all
probe goldens), fix confined to the scan loop's URI branch: slashes
split by what the path keeps (posix keeps its leading slash, drive
takes them all), localhost authority consumed with it. Probe after:
CORE 154/154, EXT FAILs 13 -> 8 (dotdot x3, encoded-uri, unc-case,
long x2, short-name -- all pre-declared). Root-literal grep of ALL
probe rows: only root-in-url and root-after-word, both POLICY PASS by
design (web-URL protection, word-boundary grammar).
Full suite 4624 passed, 2 skipped.
