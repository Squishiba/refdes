"""Run-5 release-gate friction findings F1, F2, F6 and F8.

Each test here fails on `main` as of 6251ab5 and pins the fix. The findings are
written up in `in-prog-logs/user-sim-release-gate-run5.md` §6; the one-line
version of each:

  F1  `audit` printed `ok  hash-only` for a pin whose page numbers were never
      checked, because the lockfile's `page_count_error:` is not mentioned
      anywhere in the report. `#147` exists because "audit claiming it checked"
      was the problem; this is the same claim one level up.
  F2  pypdf's own logger put a bare `EOF marker not found` on stderr, with no
      file, no path and no remedy, immediately above refdes's own warning about
      the same failure. It reads as the tool crashing and then recovering.
  F6  one unreachable citation is said twice: once naming the url, once as a
      summary that repeats it. With two urls the summary earns its line, but
      the *diagnosis* it carries is said three times.
  F8  one condition -- a key no live item declares -- was reported with three
      wordings, and two of them dropped the `refdes keys restore` command the
      third spelled out.

The round-2 review findings are tested here too, under the same discipline: each
test fails on the round-1 head, and the comments say which finding it pins.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
import random
import re
import subprocess
import sys
import textwrap
import threading

import pytest
import yaml
from conftest import write_project_config

from refdes import build as build_mod
from refdes import citations as citations_mod
from refdes import cli as cli_mod
from refdes import keys, parse
from refdes.schema import load_project

SCHEMA = """\
site: {title: "Run5 friction", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
history: {default: invalidate}
units: {preferred: []}
link_types:
  refines: { inverse: refined_by, label: "Refines" }
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      datasheets: { type: citations, on_change: invalidate }
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      title: { type: text, required: true, on_change: invalidate }
    links:
      refines: [requirement]
    body: { on_change: invalidate }
"""

DEAD = "http://127.0.0.1:1/bad.pdf"
LIVE = "http://127.0.0.1:1/good.pdf"
NOT_A_PDF = b"%PDF-1.4 not really a pdf at all, sorry\n"
PAGE_COUNT_ERROR = (
    "counting a document's pages failed: pypdf could not read the PDF: "
    "Stream has ended unexpectedly"
)


def _citation_project(root, *urls: str, pages: bool = True) -> str:
    """One component per url, each citing `page: "99"` of it -- or citing no
    page at all, which is the shape that must not be reported as having an
    unchecked page number."""
    write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    cited_page = '        page: "99"\n' if pages else ""
    rows = "".join(
        f"  - id: CMP-{i:03d}\n    title: Part {i}\n    datasheets:\n"
        f"      - path: {url}\n        rev: C\n{cited_page}"
        for i, url in enumerate(urls, start=1)
    )
    (root / "items" / "cmp.yaml").write_text(
        f"defaults:\n  type: component\nitems:\n{rows}", encoding="utf-8"
    )
    return str(root / "refdes-project.yaml")


def _mixed_page_project(root, url: str) -> str:
    """One path cited twice: CMP-001 cites a `page:` of it, CMP-003 cites it with
    no page. `audit` groups rows by path, so this is the only shape where a
    `pages unchecked` row's `cited by` column can over-claim."""
    write_project_config(root, SCHEMA)
    (root / "items").mkdir()
    (root / "items" / "cmp.yaml").write_text(
        "defaults:\n  type: component\nitems:\n"
        "  - id: CMP-001\n    title: Part 1\n    datasheets:\n"
        f"      - path: {url}\n        rev: C\n        page: \"99\"\n"
        "  - id: CMP-003\n    title: Part 3\n    datasheets:\n"
        f"      - path: {url}\n        rev: C\n",
        encoding="utf-8",
    )
    return str(root / "refdes-project.yaml")


def _pin(root, urls, extra_by_url=None, **extra) -> None:
    """One hash-only record per url. `extra` is what the fetch could not
    decide -- `page_count`, or the reason there is no page count -- and
    `extra_by_url` overrides that per url, for a project whose two citations
    are in two different states at once."""
    path = root / ".refdes" / "citations.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "citations": {
                    url: {
                        "sha256": hashlib.sha256(url.encode()).hexdigest(),
                        "fetched": "2026-01-01T00:00:00Z",
                        "kept_copy": False,
                        **extra,
                        **(extra_by_url or {}).get(url, {}),
                    }
                    for url in urls
                }
            }
        ),
        encoding="utf-8",
    )


def _run(capsys, config, *args):
    code = cli_mod.main(["-c", config, *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _said_unreachable(lines):
    """The lines that say a pinned citation could not be re-fetched, in either
    of the two shapes the refresh report uses."""
    return [
        line
        for line in lines
        if "could not refresh" in line or "could not be refreshed" in line
    ]


def _audit_rows(out, *citers):
    """The audit report's citation rows, verbatim -- leading spaces and all --
    so a test can be about the columns and not only the words."""
    rows = [
        line
        for line in out.splitlines()
        if any(line.rstrip().endswith(f"cited by {c}") for c in citers)
    ]
    assert len(rows) == len(citers), out
    return rows


def _audit_row(out):
    """The audit report's citation row for CMP-001, column-aligned in the real
    output and field-split here so the test is about the words."""
    lines = [line for line in out.splitlines() if "cited by CMP-001" in line]
    assert len(lines) == 1, out
    return " ".join(lines[0].split())


# ---------------------------------------------------------------- F1 -- audit


def test_audit_does_not_call_an_uncheckable_pin_ok(tmp_path, capsys):
    """The lockfile says these bytes have no countable pages, so no cited
    `page:` was ever compared to anything. `audit` used to print `ok`."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count_error=PAGE_COUNT_ERROR)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    row = _audit_row(out)
    assert not row.startswith("ok "), row
    assert row.startswith("pages unchecked "), row
    # and the report says why, in the words the lockfile already holds
    assert PAGE_COUNT_ERROR in out, out


def test_audit_still_calls_a_counted_pin_ok(tmp_path, capsys):
    """The fix is about the ambiguous pin, not about being generically gloomier:
    a document whose pages WERE counted keeps its `ok`."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count=8)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).split()[0] == "ok", out


def test_a_citation_citing_no_page_has_no_unchecked_page_number(tmp_path, capsys):
    """`check` reports an uncountable document once per cited `page:` --
    `_apply_page` never reaches the count for a citation without one -- so a
    citation citing no page has nothing unchecked, and `audit` must not say it
    does. The lockfile cannot decide this on its own: `fetch` writes the failed
    count against the path, and deleting the `page:` from the item leaves the
    record as it was, so the row would otherwise keep reporting a page number
    nobody cites any more."""
    config = _citation_project(tmp_path, DEAD, pages=False)
    _pin(tmp_path, [DEAD], page_count_error=PAGE_COUNT_ERROR)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).startswith("ok "), out
    assert "pages unchecked" not in out, out
    assert "no cited page number was checked" not in out, out


def test_the_pages_unchecked_row_does_not_shift_the_pin_column(tmp_path, capsys):
    """`pages unchecked` is longer than every state it replaces, so the state
    column is as wide as the widest thing it can print. A second column that
    starts one space along on one row of a report is read as a different
    column, which is the mistake this report's own history is about."""
    config = _citation_project(tmp_path, DEAD, LIVE)
    _pin(
        tmp_path,
        [DEAD, LIVE],
        extra_by_url={
            DEAD: {"page_count_error": PAGE_COUNT_ERROR},
            LIVE: {"page_count": 8},
        },
    )
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    unchecked, counted = _audit_rows(out, "CMP-001", "CMP-002")
    assert unchecked.split()[:2] == ["pages", "unchecked"], unchecked
    assert counted.split()[0] == "ok", counted
    assert unchecked.index("hash-only") == counted.index("hash-only"), (
        unchecked,
        counted,
    )


# ------------------------------------------------------------------ F2 -- pypdf


def test_refdes_reads_the_pdf_so_refdes_owns_the_report(capsys, caplog):
    """pypdf logs `EOF marker not found` to its own logger, which reaches
    stderr through logging's last-resort handler: a bare line with no file, no
    path and no remedy, right above the refdes warning about the same bytes.
    Nothing may reach the terminal from a read refdes is performing."""
    with caplog.at_level(logging.WARNING), pytest.raises(
        citations_mod.SectionError
    ) as caught:
        citations_mod.page_count(NOT_A_PDF)
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    assert captured.out == "", captured.out
    # ...and nothing escapes to the application's logging either, which is how
    # the bare line got printed in the first place: a library logger with no
    # handler anywhere above it is printed by Python's last-resort handler.
    assert [r.name for r in caplog.records if r.name.startswith("pypdf")] == []
    # nothing is lost: pypdf's own words survive, inside the message
    assert "EOF marker not found" in str(caught.value), caught.value
    assert "Stream has ended unexpectedly" in str(caught.value), caught.value


def test_a_caller_that_asked_pypdf_to_be_quiet_stays_quiet():
    """The routing adds a handler and nothing else.

    A logger is global state and `refdes serve` is threaded, so setting the
    pypdf level for the duration of one read is a setting every other thread
    sees -- and one that overrules what the caller asked pypdf for. The cost
    of leaving it alone is stated here rather than hidden: a caller that put
    pypdf below WARNING does not get pypdf's words handed to it inside refdes's
    message either, and gets the exception's own words, which is the whole
    message minus the detail it chose to silence."""
    logger = logging.getLogger("pypdf")
    handlers = list(logger.handlers)
    logger.setLevel(logging.ERROR)
    try:
        with pytest.raises(citations_mod.SectionError) as caught:
            citations_mod.page_count(NOT_A_PDF)
    finally:
        logger.setLevel(logging.NOTSET)
    assert list(logger.handlers) == handlers  # the capture handler comes back off
    assert "Stream has ended unexpectedly" in str(caught.value), caught.value
    assert "EOF marker not found" not in str(caught.value), caught.value


def test_fetch_says_what_to_do_about_uncountable_pages(tmp_path, monkeypatch, capsys):
    """The line that survives F2's routing is the one the author reads, so it
    has to carry the remedy the `check`-time wording already carries."""
    config = _citation_project(tmp_path, DEAD)
    monkeypatch.setattr(
        citations_mod, "fetch_bytes", lambda url, timeout=30.0: NOT_A_PDF
    )
    code, _out, err = _run(capsys, config, "fetch")
    assert code == 0, err
    lines = [line for line in err.splitlines() if "EOF marker not found" in line]
    assert len(lines) == 1, err  # one line, not a bare one plus a warning
    assert DEAD in lines[0], lines[0]
    assert "refdes fetch --update" in lines[0], lines[0]


# ------------------------------------------------------------------- F6 -- refresh


def test_unreachable_refresh_is_said_once(tmp_path, monkeypatch, capsys):
    """One unreachable citation, two warnings saying it: the per-url line and a
    summary that repeats it. The summary only earns its line when there is more
    than one url to count."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    said = _said_unreachable(combined.splitlines())
    assert len(said) == 1, combined
    # and that one line keeps both halves: which url, and the escape hatch
    assert DEAD in said[0], said[0]
    assert citations_mod.ALLOW_UNREACHABLE_FLAG in said[0], said[0]


def test_several_unreachable_urls_are_still_counted(tmp_path, monkeypatch, capsys):
    """With two urls the summary is the only place the count lives, so it stays
    -- and each url is still named exactly once."""
    config = _citation_project(tmp_path, DEAD, LIVE)
    _pin(tmp_path, [DEAD, LIVE])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    assert combined.count(DEAD) == 1, combined
    assert combined.count(LIVE) == 1, combined
    said = _said_unreachable(combined.splitlines())
    assert len(said) == 3, combined  # two urls and the count, not four lines
    assert "2 pinned citations could not be refreshed" in combined, combined


# -------------------------------------------------------------------- F8 -- keys


def _dead_fetcher(url, timeout=30.0):
    raise OSError("[Errno 111] Connection refused")


def _keyless_project(tmp_path):
    """A project with one live item that declares no key at all."""
    config = write_project_config(tmp_path, SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "req.yaml").write_text(
        "defaults:\n  type: requirement\nitems:\n"
        "  - id: REQ-001\n    title: Keyless\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(config))
    parse.load_items(project)
    build_mod.compute_hashes(project)
    return project


def _wording(message: str) -> str:
    """What is left of a diagnostic once the parts that legitimately vary are
    removed: which key and label are named, the one extra fact about a live
    item that carries the label (a fact, not a wording -- and
    docs/troubleshooting.md promises it), the argument of the restore command,
    which is a value, and the words telling the author to substitute the one
    part of it a bare-key reference cannot know."""
    tail = message.split("which no item declares. ")[1]
    tail = re.sub(r"^A live item labelled \S+ .*?different item\. ", "", tail)
    tail = tail.replace(", replacing DISPLAY-ID with the item's display id", "")
    return re.sub(r"restore \S+ --dry-run", "restore <target> --dry-run", tail)


def test_one_wording_for_a_key_no_item_declares(tmp_path):
    """Three wordings, one condition. The remedy the report itself gives
    (`docs/troubleshooting.md`: `refdes keys restore`) was spelled out in one
    wording and dropped in the other two, so the same trap sent an author to
    git history from one reference and to the right command from another."""
    project = _keyless_project(tmp_path)
    messages = [
        build_mod._unknown_key_message(project, "refines points at", target)
        for target in (f"REQ-001@{keys.mint()}", f"REQ-999@{keys.mint()}", keys.mint())
    ]
    for message in messages:
        assert "which no item declares." in message, message
        assert "keys restore" in message, message
    # one wording, not three: the explanation and the remedy are the same text
    tails = {_wording(message) for message in messages}
    assert len(tails) == 1, tails


def test_the_restore_command_is_spelled_out_for_a_composite_reference(tmp_path):
    """Not a placeholder and not a paraphrase: the command, with this
    reference's own label and key in it, ready to paste."""
    project = _keyless_project(tmp_path)
    original = keys.mint()
    message = build_mod._unknown_key_message(
        project, "refines points at", f"REQ-001@{original}"
    )
    assert f"run `refdes keys restore REQ-001@{original} --dry-run`" in message, message


def test_a_bare_key_says_its_command_argument_is_a_placeholder(tmp_path):
    """`DISPLAY-ID@` stands for the label, not for the key: a bare key carries
    no label, and which item the key belonged to is precisely what the author
    has to go and find out. So the message says that in words instead of printing
    a line that fails when pasted -- and keeps naming the command, which is what
    F8 was about."""
    project = _keyless_project(tmp_path)
    bare = keys.mint()
    message = build_mod._unknown_key_message(project, "refines points at", bare)
    assert f"run `refdes keys restore DISPLAY-ID@{bare} --dry-run`" in message, message
    assert "replacing DISPLAY-ID with the item's display id" in message, message


# ---------------------------------------------- round 2 -- F2/finding 1: the record

# A byte pattern, not a mock. `random.Random(seed)` makes the damage reproducible
# and `helpers.pdf_bytes` makes the document reproducible, so this file is the
# same on every machine. It is a document pypdf cannot open *and* narrates in a
# log line -- for this shape, one of those lines quotes the live address of an
# object it found: `Root found at IndirectObject(1, 0, <address>)`. Forty flips was
# the count that reached it; the count is part of the fixture, not a tuning knob,
# because the tests below assert a property of the recorded reason rather than any
# particular pypdf version's wording.
_DAMAGED_SEED = 3
_DAMAGED_FLIPS = 40


def _damaged_pdf() -> bytes:
    """A one-page PDF with `_DAMAGED_FLIPS` bytes overwritten at seeded offsets."""
    import helpers

    rng = random.Random(_DAMAGED_SEED)
    out = bytearray(helpers.pdf_bytes(helpers.pdf_page("hello")))
    for _ in range(_DAMAGED_FLIPS):
        out[rng.randrange(len(out))] = rng.randrange(256)
    return bytes(out)


def _recorded_reason() -> str:
    """What `page_count` would put in the lockfile for `_damaged_pdf()`."""
    with pytest.raises(citations_mod.SectionError) as caught:
        citations_mod.page_count(_damaged_pdf())
    return str(caught.value)


def test_the_recorded_reason_survives_a_reload_byte_for_byte():
    """Round 2, finding 1: the reason is written into `.refdes/citations.yaml`,
    which is a committed file, so the same bytes have to produce the same reason
    every time. Folding every line pypdf logged made it 1.3 KB and different on
    every run, because pypdf narrates its own recovery and one of those lines
    quotes the address of an object it found.

    So what is under test is not pypdf's wording -- it is that nothing which
    differs between two runs of the same bytes survives into the record."""
    exc = RuntimeError("Stream has ended unexpectedly")
    first = citations_mod._unreadable_reason(
        exc, ["EOF marker not found", "Root found at IndirectObject(2, 0, 139905524280560)"]
    )
    second = citations_mod._unreadable_reason(
        exc, ["EOF marker not found", "Root found at IndirectObject(2, 0, 140251244293360)"]
    )
    assert first == second, (first, second)


def test_the_recorded_reason_keeps_the_address_out():
    """The address is the part that moves between runs, and it is the whole
    reason the record changed. Object number and generation stay: those identify
    the object, and unlike its address they are stable."""
    reason = citations_mod._unreadable_reason(
        RuntimeError("Stream has ended unexpectedly"),
        ["Root found at IndirectObject(2, 0, 139905524280560)"],
    )
    assert "139905524280560" not in reason, reason
    assert "(2, 0)" in reason, reason


def test_the_recorded_reason_is_bounded():
    """Round 2, finding 1, second half: it is a lockfile value reprinted by
    `check` and `audit`, not a transcript of the parser. pypdf logged 26
    distinct lines for the fixture above, and one of its *single* lines embeds a
    whole dict repr -- `Expecting a NameObject for key but found {'/F1':
    IndirectObject(...)}` -- so keeping only the first line is not by itself a
    bound. One long line is what this needs, and that is the shape that would
    otherwise reach the file."""
    reason = citations_mod._unreadable_reason(
        RuntimeError("boom"),
        ["Expecting a NameObject for key but found " + ", ".join(
            f"'/Key{i}': IndirectObject({i}, 0, {1000000000000 + i})"
            for i in range(20)
        )],
    )
    assert len(reason) <= citations_mod.UNREADABLE_REASON_MAX, (len(reason), reason)
    # bounded by saying so, not by cutting mid-word with nothing to show
    assert reason.endswith("…"), reason
    # ...and the part that was kept still says what went wrong
    assert reason.startswith("pypdf could not read the PDF:"), reason


def test_only_the_line_that_names_the_damage_is_folded_in():
    """F2 asked for pypdf's *logged* words because the exception it finally
    raises only says the stream ended while the log says why -- `EOF marker not
    found`. One line is that fact. The lines after it are pypdf narrating its
    recovery attempt, and one of those is the address repr, so the fold stops at
    the first line and keeps the damage rather than the commentary."""
    reason = citations_mod._unreadable_reason(
        RuntimeError("Stream has ended unexpectedly"),
        [
            "EOF marker not found",
            "incorrect startxref pointer(291)",
            "trying to reconstruct xref table...",
            "Root found at IndirectObject(2, 0, 139905524280560)",
        ],
    )
    assert "EOF marker not found" in reason, reason
    assert "incorrect startxref" not in reason, reason
    assert "reconstruct xref" not in reason, reason


def test_two_processes_record_the_same_reason_for_the_same_bytes():
    """The end-to-end shape of the finding, and the only test that can catch it:
    ASLR means the address differs between *processes*, not within one, so an
    in-process test cannot see the bug at all -- CPython hands back the same freed
    address every time. Two interpreters, the same bytes, and the string that goes
    into the lockfile.

    Five processes of this on the round-1 head produced five different
    `page_count_error` values; the review's own diff shows the address changing in
    the committed file between two `refdes fetch` runs.
    """
    script = textwrap.dedent(
        """
        import random
        import sys

        sys.path.insert(0, {tests!r})
        sys.path.insert(0, {src!r})
        import helpers
        from refdes import citations

        rng = random.Random({seed})
        out = bytearray(helpers.pdf_bytes(helpers.pdf_page("hello")))
        for _ in range({flips}):
            out[rng.randrange(len(out))] = rng.randrange(256)
        try:
            citations.page_count(bytes(out))
        except citations.SectionError as exc:
            print(exc)
        """
    ).format(
        tests=str(pathlib.Path(__file__).resolve().parent),
        src=str(pathlib.Path(citations_mod.__file__).resolve().parents[1]),
        seed=_DAMAGED_SEED,
        flips=_DAMAGED_FLIPS,
    )

    def reason_in_a_fresh_interpreter():
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    first = reason_in_a_fresh_interpreter()
    assert first, "the fixture is supposed to be unreadable"
    assert first == reason_in_a_fresh_interpreter(), (
        "same bytes, two processes, two records -- a committed lockfile would "
        "diff on every fetch"
    )
    # and the properties that make it safe to keep, asserted on the real bytes
    assert len(first) <= citations_mod.UNREADABLE_REASON_MAX, first
    assert not citations_mod._PYPDF_ADDRESS_REPR.search(first), first


# ------------------------------------------ round 2 -- F2/finding 2: threading


def test_two_overlapping_reads_leave_the_callers_logging_alone():
    """Round 2, finding 2: `propagate` is a logger the host application owns,
    and the routing was saving it per block. Two reads overlapping on two
    threads interleaved so the flag was never put back -- 300/300 in the review's
    reproduction -- leaving the host blind to pypdf for the rest of the process.

    `refdes serve` is threaded, so overlapping reads are the normal case and not
    a hypothetical one.

    The interleaving is pinned rather than raced: the second read enters while the
    first is inside, so per-block save/restore has it save the already-mutated
    `False` -- and the *second* is released first, so its restore is the one that
    lands last and the leak is the value a real server would be left with. With
    the release order left to chance the test caught this only about half the
    time, which is a test that cannot be relied on to catch it at all.
    """
    logger = logging.getLogger("pypdf")
    first_entered, second_entered = threading.Event(), threading.Event()
    release_first, release_second = threading.Event(), threading.Event()
    # A thread that dies leaves the barrier unsignalled and the wait below
    # times out, which reports a timeout instead of the real error -- so carry
    # whatever the thread raised out.
    errors: list[BaseException] = []

    def read(entered, release):
        try:
            with citations_mod._owning_pypdf_logs():
                entered.set()
                release.wait(timeout=5)
        except BaseException as exc:  # noqa: BLE001 -- reported by the test
            errors.append(exc)

    first = threading.Thread(target=read, args=(first_entered, release_first))
    first.start()
    second = threading.Thread(target=read, args=(second_entered, release_second))
    second.start()
    for entered in (first_entered, second_entered):
        if not entered.wait(timeout=5) and errors:
            break
    release_first.set()
    first.join(timeout=5)
    release_second.set()  # ...so the second's restore lands last
    second.join(timeout=5)
    assert not errors, errors

    assert logger.propagate is True, (
        "propagate leaked: a host application's logging would be blind to pypdf "
        "for the rest of the process"
    )
    assert list(logger.handlers) == [], logger.handlers


def test_a_nested_read_does_not_restore_propagation_early():
    """The same race without threads: `_unreadable_reason` is called from inside
    a read, so a nested block that restored what it saved would put the flag
    back while the outer read was still running."""
    logger = logging.getLogger("pypdf")
    with citations_mod._owning_pypdf_logs():
        with citations_mod._owning_pypdf_logs():
            pass
        # the outer block is still reading here, so pypdf must still be muted
        assert logger.propagate is False, logger.propagate
    assert logger.propagate is True, logger.propagate


def test_a_caller_who_turned_propagation_off_gets_it_back_off():
    """The routing is a mutation of something the caller owns, so what it must
    restore is the caller's setting, not refdes's opinion of it. A host that
    muted pypdf before calling in is not un-muted afterwards."""
    logger = logging.getLogger("pypdf")
    logger.propagate = False
    try:
        with citations_mod._owning_pypdf_logs():
            pass
        assert logger.propagate is False, logger.propagate
    finally:
        logger.propagate = True


def test_one_reads_words_do_not_land_in_anothers_message():
    """The handler is attached to the one `pypdf` logger and a log record does
    not say which read produced it, so two concurrent reads used to fold each
    document's complaint into both reasons. A message naming one document's
    damage, quoted in another document's error, is worse than no detail."""
    logger = logging.getLogger("pypdf")
    inside = threading.Barrier(2)
    got: dict[str, list[str]] = {}

    def read(name: str):
        with citations_mod._owning_pypdf_logs() as logged:
            logger.warning(f"{name} is damaged")
            inside.wait(timeout=5)  # let both records land while both are live
        got[name] = list(logged)

    threads = [
        threading.Thread(target=read, args=(name,))
        for name in ("CMP-001", "CMP-002")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert got["CMP-001"] == ["CMP-001 is damaged"], got
    assert got["CMP-002"] == ["CMP-002 is damaged"], got


# ------------------------------------------- round 2 -- F6/finding 5: diagnosis


def test_two_unreachable_urls_are_diagnosed_once(tmp_path, monkeypatch, capsys):
    """Round 2, finding 5: with two urls the summary line is the one place the
    shared diagnosis belongs, because it is the only line that speaks for both.
    Saying it on each url's line as well is three repetitions of one sentence
    where the baseline had one -- and F6 is precisely the finding that said so."""
    config = _citation_project(tmp_path, DEAD, LIVE)
    _pin(tmp_path, [DEAD, LIVE])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    assert combined.count("upstream drift was NOT verified") == 1, combined
    # and the remedy survives on the summary line, so nothing is lost
    assert citations_mod.ALLOW_UNREACHABLE_FLAG in combined, combined


def test_two_unreachable_urls_are_diagnosed_once_when_the_run_fails(
    tmp_path, monkeypatch, capsys
):
    """Same, on the error path -- no `--allow-unreachable`, so this is the shape
    that fails the run and is the one a release reviewer actually hits."""
    config = _citation_project(tmp_path, DEAD, LIVE)
    _pin(tmp_path, [DEAD, LIVE])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh")
    combined = out + err
    assert code != 0, combined
    assert combined.count("upstream drift was NOT verified") == 1, combined


def test_one_unreachable_url_still_carries_the_diagnosis_and_the_remedy(
    tmp_path, monkeypatch, capsys
):
    """Gating it on `n == 1` must not lose it where it is the only place it is
    said: with one url the summary line is gone, so the per-url line has to
    carry both the diagnosis and the way out."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD])
    monkeypatch.setattr(citations_mod, "fetch_bytes", _dead_fetcher)
    code, out, err = _run(capsys, config, "check", "--refresh", "--allow-unreachable")
    combined = out + err
    assert code == 0, combined
    said = _said_unreachable(combined.splitlines())
    assert len(said) == 1, combined
    assert "upstream drift was NOT verified" in said[0], said[0]
    assert citations_mod.ALLOW_UNREACHABLE_FLAG in said[0], said[0]


# ---------------------------------------- round 2 -- F1 nit 7: who the row names


def test_the_pages_unchecked_row_names_only_citers_that_cite_a_page(tmp_path, capsys):
    """Round 2, nit 7: rows are grouped by path, so one row can cover a
    page-citing citer and a page-less one, and the sentence under it says "no
    cited page number was checked" -- which for the page-less citer is F1's own
    mistake pointed at the reader.

    The page-less citer is still named, on its own line: dropping it would take
    the report's only record that CMP-003 cites this path at all, which is the
    same invisible-suppression fault from the other direction."""
    config = _mixed_page_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count_error=PAGE_COUNT_ERROR)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    row = _audit_row(out)
    assert row.startswith("pages unchecked "), row
    assert row.endswith("cited by CMP-001"), row
    assert "CMP-003" not in row, row
    # ...and it is named, with the fact it alone has
    assert "CMP-003 cites this path without a page number" in out, out
    # nothing is claimed about a page number CMP-003 never cited
    assert "no cited page number was checked" in out, out


def test_a_row_with_every_citer_citing_a_page_names_them_all(tmp_path, capsys):
    """The extra line is for the mixed case only. A path whose every citer cites
    a page prints the row it always printed, with no trailing note."""
    config = _citation_project(tmp_path, DEAD)
    _pin(tmp_path, [DEAD], page_count_error=PAGE_COUNT_ERROR)
    code, out, err = _run(capsys, config, "audit")
    assert code == 0, err
    assert _audit_row(out).endswith("cited by CMP-001"), out
    assert "without a page number" not in out, out
