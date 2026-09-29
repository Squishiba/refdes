# perf: re-baseline after the markdown-it fix, and what Opportunity 3 is actually worth

Measurement and analysis only. No change to `src/`, `tests/`, or any tracked
file. Harness and corpora live in `.scratch/` (gitignored) and are listed in §12.

Plan under review: `.scratch/refdes-optimization-plan.txt` §7 step 3 — "re-measure,
then decide between opportunity 2 (not mine, untouched) and opportunity 3 with
fresh profiles". Opportunity 2 / `serve/edit.py` was not touched by this pass.

## 1. Does `refdes` work here — the editable install

`pip show refdes` in the shared venv:

    Editable project location: /home/jorb/.paseo/worktrees/16msma8v/user-sim-release-gate-run2b

So the `/tmp/w-pr59-merge` path the planning pass hit is gone, but the install
now points at **another live worktree** — `refdes ...` runs *that* checkout's
`src/`, not this one's. Repointing it would move the ground under the other
sessions sharing the venv, so I did not. Everything below ran against **this**
worktree's `src/` two ways, both verified:

- in-process: `sys.path.insert(0, "<this worktree>/src")` + `refdes.cli.main()`;
- subprocess (for real end-user wall time): `.scratch/clirun.py`, which does the
  same insert and then calls `refdes.cli.main()`.

`import refdes.__file__` was asserted to resolve under this worktree in every
harness. `pytest` is unaffected (`tests/conftest.py` bootstraps `../src`).

Machine: 20 CPUs, load average 1.73 at measurement time — mostly idle, but other
workers were live in other worktrees, so treat every absolute as ±5-10%.

## 2. Corpus and harness, same shape as the planning pass

`.scratch/mkperfproj.py` reproduces §3 exactly: copy of the real
`refdes-project.yaml` minus `boards:`/`workspaces:`/`equations:`, standard
`hardware@3`, N `requirement` items (`prefix: REQ-PERF`) in 50-item YAML files,
each `refines:` the previous id. N = 100 / 400 / 1600. `check`, `index`, `build`
all exit 0. Best-of-5 for the table (the planning pass used best-of-3), best-of-3
for the what-if runs.

Two extra corpora for §6/§7: `.scratch/perfflat-1600-0` (same N, **no** `refines:`
at all) and `.scratch/realproj` (a copy of this repo's own project).

## 3. New numbers next to the old ones

CLI, in-process, best-of-N, ms:

| N | metric | plan §3 (before fix) | this pass (after fix) | Δ |
|---|---|---|---|---|
| 100 | `check` | 36 | **22.7** | −37% |
| 100 | `index` | 37 | **25.9** | −30% |
| 100 | `build` | 167 | **153.9** | −8% |
| 100 | `load_readonly` | 31 | **17.9** | −42% |
| 400 | `check` | 104 | **55.7** | −46% |
| 400 | `index` | 115 | **67.9** | −41% |
| 400 | `build` | 392 | **336.1** | −14% |
| 400 | `load_readonly` | 99 | **52.4** | −47% |
| 1600 | `check` | 394 | **193.9** | −51% |
| 1600 | `index` | 431 | **235.6** | −45% |
| 1600 | `build` | 1977 | **1592.6** | −19% |
| 1600 | `load_readonly` | 379 | **188.9** | −50% |

Two runs of the N=1600 bench agreed to within 1.5% (196.8/237.8/1594.3/190.1 and
193.9/235.6/1592.6/188.9), and both agree with the landed fix's own report
(check 188.6, index 231.6, load_readonly 186.6) to within ~5%. The "before"
column is the planning machine, so cross-machine deltas carry that ±10% caveat.

Real subprocess `refdes build` at N=1600 (interpreter start + imports included):
**2053 ms** best-of-5 — i.e. ~460 ms of the user-visible wall is Python startup,
which no in-process number shows.

Scaling is still ~linear on the load side (0.120 ms/item at 1600, was 0.24). CLI
`build` per item: 1.54 / 0.84 / 0.99 ms — still no confirmed quadratic in
100..1600, and §6 finds the one thing that *is* quadratic is output bytes, not time.

## 4. Regression check: did the predicted −40-45% model-build win materialize?

**Yes — it over-delivered.** Three independent checks:

1. **Phase breakdown of load+build at N=1600** (best-of-5, total 198 ms):

   | phase | plan (before) | now | |
   |---|---|---|---|
   | `load_project(schema)` | 6.4 ms (1.6%) | 6.2 ms (3.2%) | — |
   | `parse_items` | 40.6 ms (10.4%) | 41.0 ms (20.8%) | — |
   | `keys.mint_missing` | 3.5 ms (0.9%) | 3.6 ms (1.8%) | — |
   | `links.*` + freeze | 2.8 ms (0.7%) | 3.7 ms (1.9%) | — |
   | **`build.build`** | **334.6 ms (86.1%)** | **143.0 ms (72.4%)** | **−57%** |

   Plan predicted 335 → ~185 ms (−45%). Landed report measured 320 → 132 ms.
   This pass measures **143.0 ms** on a different day in a different worktree.
   `parse_items` is now the second-biggest phase at 21%, exactly as the landed
   report said it would be.
2. **Construction count.** `.scratch/probe-mdcount.py` patches
   `MarkdownIt.__init__` to count: **1** construction per `load_readonly` at
   N=1600 (was 1602), and still 1 after a second load in the same thread. Last
   construction args `('gfm-like', {'html': False, 'linkify': False})` — the
   configuration is still byte-identical to the pre-fix literal.
3. **Profile shape.** Full-CLI cProfile at N=1600: 7,614,631 calls now vs
   8,653,541 in the planning pass (−12%), and both markdown-it construction
   entries that were in the old top 25 (`markdown_it/ruler.py:176 push`,
   `inspect.py:579 _getmembers`) are gone from it.

No regression: the fix is still doing what it claimed, on this worktree.

## 5. Where `refdes build` time goes now (N=1600, best-of-5)

Attribution by wrapping the coarse seams (no cProfile overhead), wall best =
1685 ms in that harness / 1592.6 ms uninstrumented:

| phase | ms | % of build wall |
|---|---|---|
| `load_tree` (parse, keys, links) | 55.1 | 3.3% |
| `build.build` (model) | 136.0 | 8.1% |
| **`render_site`** | **1459.5** | **86.6%** |
| `cli._report` | 0.0 | 0% |
| unattributed | ~30 | 1.8% |
| — of which `items_json` payload | 5.0 | 0.3% |
| — of which `items.json` `json.dump(indent=2)` | 37.9 | 2.4% |

**Answer to the headline question: the site-render phase is now 86.6% of `build`**
(it was ~80% before: 1977 − 335 model − ~60 load ≈ 1580/1977). On this repo's own
real project it is already **84%** (§10). Model build is 8% of the command.

Fresh cProfile of the full CLI path at N=1600 (`wall=3.43 s` under cProfile,
`.scratch/prof-cli-build-perfproj-1600.txt`), top entries by tottime:

```
200489   0.618  {method 'write' of '_io.TextIOWrapper' objects}
176954   0.166  {built-in method __new__ of type object}
27855    0.161  {method 'join' of 'str'}
 76862   0.114  jinja2/runtime.py:262(call)
505313   0.111  json/encoder.py:334(_iterencode_dict)
166376   0.101  src/refdes/templates/item.html.j2:31(block_content)
  1667   0.101  {built-in method _io.open}
422911   0.094  src/refdes/templates/base.html.j2:4(root)
153012   0.089  markupsafe/__init__.py:24(escape)
  1666   0.084  {method '__exit__' of '_io._IOBase'}
169813   0.082  markupsafe/__init__.py:122(__new__)
     2   0.048  json/__init__.py:120(dump)   cumtime 0.270
```

**Correction to the planning pass's read of its own profile.** It reported
"`TextIOWrapper.write` 1609 calls, 0.591 s, from `render.py`'s `_write_html`".
Its own profile actually shows **200,489** write calls, and `.scratch/probe-write-callers.py`
attributes them exactly:

- **1,609** page writes (`_write_html`, one per page — that part of the plan was
  right, and it is where the *bytes* are);
- **197,266** writes from `json.dump(items_json(project), fh, indent=2)`, averaging
  **6 bytes per write** — that is 98% of the call count and the whole of the
  `_iterencode_dict` 505,313 figure.

Those two costs are not the same size: the items.json dump in its entirety is
37.9 ms (7.3 ms of that is encoding; `json.dumps` alone measured separately).
The 0.618 s the profile shows for `write` is mostly the 574 MiB of page bytes
(§6) plus ~2 µs of profiler overhead × 200k calls. So the profile's #1 entry is
a *bytes* problem wearing a *call-count* costume, and neither (a) nor (c) is
aimed at it.

## 6. What `render_site` is actually spending 1.46 s on

Instrumenting `_write_html` to time render and write separately (per run):

| | ms | |
|---|---|---|
| jinja `template.render` | ~582 | 43% of write-through time |
| `open` + `write` + close | ~782 | 57% |
| rest of `render_site` (preview payload, `chains.build_graph`, items.json, assets, manifest) | ~90 | |

and the output it writes:

    1613 files, 575.4 MiB   (items.json 1.24 MiB; 1609 HTML pages, median 363.2 KiB)

**99.1% of every item page's bytes are the `<script id="preview-data">` block**:
359.9 KiB of a 363.2 KiB page. `render.preview_payload(project)` builds one dict
of all N items (0.35 MiB at N=1600) and `render_site` embeds that same string
into all 1609 pages. Site bytes are therefore **quadratic in item count**:

| N | output files | site bytes | item page | preview block |
|---|---|---|---|---|
| 100 | 113 | 3.2 MiB | 25.7 KiB | 87% |
| 400 | 413 | 38.5 MiB | 93.0 KiB | 96% |
| 1600 | 1613 | **575.4 MiB** | 363.2 KiB | **99%** |

This is **not** an artifact of the synthetic corpus's 1600-deep `refines:` chain.
`.scratch/perfflat-1600-0` — same 1600 items, **no `refines:` at all** — builds in
1494 ms and writes **574.3 MiB**, sample page 362.6 KiB at 99% preview block. Any
1600-item project does this.

That is the thing the planning pass's a/b/c list is missing. Call it **3(d)**.

## 7. Measured ceilings: a, b, c, and d

`.scratch/perf-whatif.py` simulates each option at the seams (patching
`render._write_html` / `render.preview_payload`) and measures the **full CLI
build**, so every row includes load + model build + render. Best-of-3, N=1600,
instrumented baseline 1713 ms (the instrumentation adds ~120 ms vs the
uninstrumented 1592.6 ms; all rows share it, so deltas are the honest part):

| simulation | best ms | Δ vs baseline | site bytes | what it is |
|---|---|---|---|---|
| baseline | 1713 | — | 575.4 MiB | today |
| **`tiny_preview`** | **760** | **−953 (−56%)** | **11.0 MiB** | **3(d): ~1 KiB payload per page instead of 360 KiB** |
| `no_preview` | 772 | −941 | 9.9 MiB | 3(d)'s absolute ceiling (zero payload) |
| `no_write` | 893 | −820 | 575.4 MiB | 3(b)'s ceiling on a *no-op* rebuild |
| `binary_write` | 1766 | −36 / −4 / +53 across runs | 575.4 MiB | 3(a) |

Same harness at N=400 (baseline 335.1 ms): `tiny_preview` −69.9 (−21%),
`no_write` −85.6, `binary_write` −2.6. At N=100 (baseline 154.8 ms): −6.7 (−4%),
−14.9, −1.9. **3(d)'s win grows superlinearly with project size** — 4% → 21% → 56%
— because the payload it removes is the quadratic term.

How much of the payload a page actually needs (`.scratch/probe-preview-subset.py`,
counting the `data-ref="…"` anchors each page really offers):

    N=1600: embedded now 565.4 MiB (359.9 KiB/page)
            needed by real refs 1.8 MiB (1.1 KiB/page)   -> 99.7% of preview bytes is dead weight
            median page: 2 refs.  worst page: 1600 refs (the aggregate pages: index/document/coverage)

3(c), `items.json`: `json.dump(indent=2)` = **37.9 ms** (2.4% of build), of which
7.3 ms is encoding; the other ~30 ms is 197k six-byte `write()` calls. A one-line
`json.dumps` + single write, or dropping `indent`, recovers most of that.

3(b), skip-unchanged pages: see §9 — the ceiling above is only reachable when
*nothing* changed.

3(a), write bytes: see §8 — measured at zero.

## 8. Byte-safety of 3(a), measured rather than reasoned about

`.scratch/probe-write-bytes.py` writes 11 samples through `open(..., "w",
encoding="utf-8")` (what `render.py` does today) and through `open(..., "wb") +
encode("utf-8")`, then diffs bytes: LF-only, no final newline, CRLF inside the
content, lone `\r`, non-ASCII (`é — − 中文 😀`), NEL `\x85` + `\u2028`, form feed /
vertical tab, tabs and entities, empty string, bare `\n`, 5000 lines.

    POSIX: text-mode and binary bytes identical for every sample: True
    newline='\r\n' (what Windows' default does) identical: False  (10 of 11 samples)

So on Linux the two paths are byte-identical — including final-newline and
embedded-CRLF behaviour. The one difference 3(a) introduces is that `wb` stops
applying Windows' default `\n` → `\r\n` translation, i.e. **every page's bytes
change on Windows and nowhere else**.

And that is a *deliberate* property, not an accident waiting to be cleaned up.
`tests/test_eol_fidelity.py:793` `TestBuildOutputIsUnchanged` says so in its
docstring: *"Site HTML and the manifest are build output, not source: they are
written in text mode on purpose so a Windows build produces Windows line
endings, and nothing in this change may start forcing LF on them."* Its one
assertion about the built site (`test_site_output_is_still_written_the_way_it_always_was`,
line 798) checks `<html` is present, no `\r\r`, and no *mixture* of endings
within a file — and states outright that CRLF-on-Windows / LF-on-Linux are both
correct. Worth flagging: **that test would not catch 3(a)**. Pure-LF output on
Windows passes "no `\r\r`" and passes "not mixed", and on Linux the bytes are
identical anyway. So 3(a) violates a stated invariant whose test guards the
intent rather than asserting it — the worst combination for a 0-2% win.

And the win is not real. `.scratch/probe-write-speed.py` writes 1609 *distinct*
files of representative page size (571 MiB per round), interleaved rounds, with
`encode()` **inside** the binary loop because that is what `render.py` would have
to do:

    text   best=  903.0 ms   all=[925, 903, 909]
    binary best=  895.6 ms   all=[899, 896, 896]
    saving: +7.3 ms per full site write

(The first version of that probe pre-encoded the bytes outside the loop and
showed a 500 ms "saving". That number is the UTF-8 encode, which 3(a) does not
avoid — it is exactly the trap in this option. The end-to-end `binary_write`
row in §7 independently says the same thing: −36 / −4 / +53 ms, i.e. noise.)

**3(a) is worth 0-36 ms (0-2%) for a Windows output-byte change with no test
coverage. Drop it.**

## 9. Feasibility of 3(b), measured

`.scratch/probe-invalidate.py`: build N=400, sha256 every output file, edit
**one** item's body, rebuild, diff.

    output files=413   changed=410   html changed: 409 of 409   unchanged: 3
    -> a per-page "inputs unchanged" cache would skip 1% of pages on a one-item edit

Every page depends on project-wide state — the preview payload, the nav/index
listings, coverage — so there is no per-page input set small enough to make a
skip cache pay. 3(b) only helps a rebuild where nothing changed, which is a
benchmark, not a workflow. And `docs/design/browser-editor.md:1120` already
defers exactly this: *"Incremental build/render optimization, only if measured
project size makes a full rebuild too slow"* — on this repo's own project a full
rebuild is 137 ms (§10).

3(b) also carries the invariant the plan flagged (`_prune_stale_output` must
never leave a live, still-linkable page behind). A skip-render path has to keep
writing the manifest for skipped files or the next prune deletes them — a
self-inflicted version of exactly that bug. High risk, ~1% payoff.

## 10. Anchor: this repo's own project

`.scratch/realproj` (a copy — nothing in the worktree was built into):

    20 items -> 45 output files, 682 KiB
    cli build best=136.9 ms   load_readonly best=17.2 ms   render_site best=114.7 ms (84% of build)
    preview-data = 231 KiB of 600 KiB HTML (39%); payload 5.8 KiB embedded once per page (40 pages)

Two things worth noting from the small end: render is *already* 84% of the
command at 20 items, and its per-page cost there (2.9 ms/page) is dominated by
fixed setup — jinja env + template compile + `chains.build_graph` — not by N.
Nobody would call 137 ms slow, which is the honest reason Opportunity 3 has no
urgency for a project of this size and every urgency for a project of 1000+.

## 11. Cross-reference to Opportunity 2 (not touched, not mine)

`serve/preview.py:86` `PreviewManager.render()` calls `render_site(project,
draft=True)` into a fresh temp generation, and `serve/api.py:525` describes the
save path as the design's "full rebuild after save". So the ~1.46 s site render
measured here sits **inside** the editor save path on top of the two model
builds Opportunity 2 is about — and it writes 575 MiB into a temp directory per
save at N=1600. Whoever owns Opportunity 2 should know the render, not the model
build, is likely the bigger half of a save. No measurement or file in this pass
touched `serve/`.

## 12. Recommendation

**Opportunity 3 is still the biggest remaining win — 86.6% of `build` at
N=1600, 84% on the repo's own project — but the plan's a/b/c ranking does not
survive the measurements. Reprioritize to a new option (d).**

1. **Do 3(d) first: embed only the previews a page actually links to, not the
   whole project's payload.** Measured −56% of full CLI build at N=1600
   (−21% at 400, −4% at 100) and a **52× smaller site** (575 MiB → 11 MiB). It
   is the only candidate whose payoff grows with project size, and it fixes a
   product problem independent of build time: a 1600-item project currently
   writes 575 MiB of HTML and hands every page's reader a 363 KiB document of
   which 99% is data that page will never show.
   - Risk is the lowest of the four *if* done as a subset rather than a fetch.
     `templates/assets/app.js` states the design intent explicitly: *"Everything
     is inlined at build time — no network calls. Without JS the refs remain
     ordinary working links, which is the whole point of doing this at build
     time rather than fetching on demand."* A per-page **subset** keeps that
     promise exactly; replacing the block with a `previews.json` fetch breaks it
     (and would need a `file://` answer).
   - Constraints a change must respect: keep the `\u003c`/`\u003e` escaping done
     at dump time (`render.py:930`) and
     `tests/test_render_assets.py:1068` `test_preview_data_escapes_script_close`;
     keep every `data-ref` on a page
     resolvable in that page's payload — a ref missing from the map degrades
     silently to "no preview", which is the one real failure mode; aggregate
     pages (index/document/coverage, which really do link to all N items) keep
     the full payload, so the win is 1609 pages → 3, not 1609 → 0.
   - Golden check that fits the change: diff every page with the
     `preview-data` block stripped — that diff must be empty — plus assert every
     `data-ref` on each page is a key of that page's payload.
2. **3(c) as a drive-by, not a pass.** 37.9 ms (2.4%). One line. Note it changes
   the bytes of a documented surface: `docs/design/browser-editor.md:629` —
   *"`items.json` remains the public read-only export"* — and
   `docs/design/calc-sources.md:777` says imported items are projections of an
   upstream `items.json`. JSON-parse-compatible either way, but it is a contract,
   so it wants a changelog fragment in the `libyaml-parsing.changed.md` style.
3. **Drop 3(a).** Measured 0-36 ms (0-2%), byte-identical on POSIX for every
   sample, but it silently changes every page's bytes on Windows by removing
   newline translation — and `tests/test_eol_fidelity.py:793` documents that
   text-mode writing of site output is *on purpose* so Windows builds get CRLF.
   The existing test would not catch the change (§8), so it is an unguarded
   violation of a stated invariant. The 500 ms figure that makes this option
   look attractive is the UTF-8 encode, which it cannot skip.
4. **Defer 3(b).** 1% of pages survive a one-item edit; the project's own design
   doc defers incremental render until a *measured* project is too slow, and the
   measured number for a real project is 137 ms. Revisit only after 3(d), and
   only if a real project of 1000+ items exists to measure — 3(d) is also the
   prerequisite that would give per-page input hashing anything to hash.
5. **Then re-measure.** After 3(d), `build` at N=1600 is ~740 ms of which model
   build is 136 ms (18%) and render ~500 ms; at that point Opportunity 2 (two
   model builds + a full preview render per save) is again the top item, and the
   remaining render cost is jinja CPU on genuinely per-page markup.

## 13. Noise and honesty

- Absolute numbers are one machine, other workers live in other worktrees; load
  average was 1.73 on 20 CPUs. Two independent N=1600 bench runs agreed within
  1.5%, and `build`'s best-of-5 spread was 171-181 ms (median 1745 vs best 1593)
  — the spread is all in the render phase. Treat absolutes as ±5-10%; the §7
  deltas are best-of-3 within one process, which is the tightest comparison here.
- The "before" column in §3 is the planning machine, not this one. The
  regression check in §4 therefore leans on the phase breakdown, the construction
  count, and the profile shape rather than on cross-machine subtraction.
- The synthetic corpus is requirements-only: no calc lines, no images, no log
  entries, no boards, no imports, no PDF sources, and `check` reports 2
  diagnostics. §6's flat-corpus run rules out the one corpus feature (the
  `refines:` chain) that could have explained the quadratic bytes; nothing here
  rules out a corpus heavy in calc/bounds checking ranking the *model-build*
  phases differently.
- The §7 rows are simulations at seams, not implementations. `tiny_preview`
  measures the cost profile of the real fix (a ~1 KiB payload per page), not its
  correctness; the subset computation itself is not in that number, and at
  median 2 refs/page it is a dict lookup per ref, so it will not eat the win.
- `--no-write` was passed to every CLI run, matching the planning harness. It
  gates seals and the membership manifest, **not** the site: `cmd_build` renders
  regardless (`cli.py:249`), so these are real render numbers.

## 14. Files left in `.scratch/` (gitignored, not committed)

`runcli.py`, `clirun.py` (this-worktree-src bootstrap, in-process and subprocess);
`mkperfproj.py`, `mkperfflat.py` (corpora); `perf-bench.py`, `perf-phases.py`,
`perf-cli-split.py`, `perf-cli-profile.py`, `perf-render-split.py`,
`perf-whatif.py`, `perf-realproj.py`; `probe-mdcount.py`, `probe-write-bytes.py`,
`probe-write-speed.py`, `probe-write-callers.py`, `probe-invalidate.py`,
`probe-preview-subset.py`; `prof-cli-build-perfproj-1600.txt`. Corpora under
`.scratch/perfproj-{100,400,1600}/`, `.scratch/perfflat-1600-0/`,
`.scratch/perfinv-400/`, `.scratch/realproj/`, `.scratch/wb-bytes/`,
`.scratch/wspd/` — all regenerable, safe to delete.
