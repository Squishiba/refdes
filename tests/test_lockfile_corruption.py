"""A `.refdes/citations.yaml` that cannot be read is a diagnostic, not a traceback.

Finding F5 of `in-prog-logs/remote-fetch-exercise.md`: a lockfile holding a
list under `citations:` -- the shape a botched merge of two branches that both
ran `refdes fetch` leaves behind -- produced a raw
`ValueError: dictionary update sequence element #0 has length 21` out of both
`refdes fetch` and `refdes check`, because `load_lockfile` handed whatever it
parsed straight to `dict()`.

The file is committed and hand-mergeable (`docs/cli-reference.md`, "Files the
tool writes"), so this is not a hand-edit nobody would make: it is the ordinary
outcome of a merge resolved badly. Every shape here is what that leaves behind,
and each one has to say so rather than raise.

Three properties per shape, at both readers named in the finding:

- no traceback -- the command reports and returns a code;
- the diagnostic names `.refdes/citations.yaml` (and the line, where the shape
  gives one);
- the corrupt file is left **byte-identical**, which is the whole point for
  `fetch`: it is the one command that writes this file, so a lockfile it
  rewrote from records it could not read would lose every pin it did not just
  re-fetch, with nothing left in the tree to say so.
"""

from __future__ import annotations

import json
import os

import pytest
from conftest import write_project_config

from refdes import citations as citations_mod
from refdes import cli as cli_mod

PROJECT = """\
site: { title: Lockfile Corruption, out: _site }
id: { width: 3, ledger: .refdes/ids.yaml }
types:
  component:
    prefix: CMP
    label: Component
    fields:
      title:      { type: text, required: true, on_change: invalidate }
      citations: { type: citations, on_change: invalidate }
"""

ITEMS = """\
defaults: { type: component }
items:
  - id: CMP-001
    title: Buck converter
    citations:
      - path: https://www.example.com/ds.pdf
        rev: E
        page: "14"
        keep_copy: false
"""

CITE = "https://www.example.com/ds.pdf"
SHA = "6b27cbc00d3de5f5b838cab15a37c5b136b835e43fdaf98bac290015b862bc50"

# One entry per corruption shape. The first three are the ones F5 names; the
# rest are the neighbouring shapes of the same file, each of which used to be
# either a traceback or -- worse, for the field-level ones -- a silent success
# that read the record as if it were sound.
SHAPES: dict[str, str] = {
    "merge-markers": (
        "<<<<<<< HEAD\n"
        "citations:\n"
        f"  {CITE}:\n"
        f"    sha256: {SHA}\n"
        "=======\n"
        "citations:\n"
        "  https://www.example.com/other.pdf:\n"
        f"    sha256: {'b' * 64}\n"
        ">>>>>>> other-branch\n"
    ),
    "invalid-yaml": (
        "citations:\n"
        f"  {CITE}:\n"
        f"    sha256: '{SHA}'\n"
        "   bytes: 1\n"
    ),
    "citations-list": f"citations:\n  - {CITE}\n",
    "citations-scalar": "citations: whatever\n",
    "document-is-a-list": "- one\n- two\n",
    "document-is-a-scalar": "just a string\n",
    "record-is-a-scalar": f"citations:\n  {CITE}: nope\n",
    "record-missing-sha256": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
    ),
    "sha-not-hex": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        "    sha256: 'not-a-digest'\n"
    ),
    # The shape F2 of the report notes YAML produces on its own: 64 zeros
    # unquoted is the integer 0, not a digest, and the record read as pinned
    # with no hash at all.
    "sha-read-as-an-integer": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: {'0' * 64}\n"
    ),
    "bytes-is-a-string": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: '509'\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
    ),
    "kept-copy-is-a-string": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: 'yes'\n"
        f"    sha256: '{SHA}'\n"
    ),
    "sections-not-a-mapping": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
        "    sections: nowhere\n"
    ),
    "values-not-a-mapping": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
        "    values: [a, b]\n"
    ),
    # A repeated key is the shape that loses a pin without a word: YAML resolves
    # a mapping with a repeated key to the last one and says nothing, so a
    # lockfile holding two sound records for one cited path reads as though only
    # one was ever pinned -- and `refdes fetch`, which rewrites the file from the
    # mapping it loaded, would go on writing one of them back forever. Both
    # records below are complete on purpose: an incomplete one is caught by the
    # missing-field checks, which is how this shape was found only by accident.
    "duplicate-record": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
        f"  {CITE}:\n"
        "    bytes: 511\n"
        "    fetched: '2026-01-02T00:00:00Z'\n"
        "    kept_copy: true\n"
        f"    sha256: '{SHA}'\n"
    ),
    "duplicate-citations-block": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
        "citations:\n"
        "  datasheets/other.pdf:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
    ),
    # A repeat that agrees with itself loses nothing, and saying otherwise would
    # be the one wrong thing in a message whose job is to be believed.
    "duplicate-record-identical": (
        "citations:\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
        f"  {CITE}:\n"
        "    bytes: 509\n"
        "    fetched: '2026-01-01T00:00:00Z'\n"
        "    kept_copy: false\n"
        f"    sha256: '{SHA}'\n"
    ),
    # Two occurrences on one line, in flow style. "(lines 1 and 1)" would read
    # like a bug in the diagnostic rather than in the file.
    "duplicate-flow-one-line": (
        f"citations: {{{CITE}: {{sha256: '{SHA}'}}, {CITE}: {{sha256: '{SHA}'}}}}\n"
    ),
}

SHAPE_IDS = list(SHAPES)


@pytest.fixture
def project(tmp_path):
    """A one-item project citing one URL, with a *sound* lockfile to corrupt."""
    config = write_project_config(tmp_path, PROJECT)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "cmp.yaml").write_text(ITEMS, encoding="utf-8")
    lock = tmp_path / ".refdes" / "citations.yaml"
    lock.parent.mkdir(exist_ok=True)
    lock.write_text(
        citations_mod.lockfile_text(
            {
                CITE: {
                    "sha256": SHA,
                    "fetched": "2026-01-01T00:00:00Z",
                    "kept_copy": False,
                    "bytes": 509,
                }
            }
        ),
        encoding="utf-8",
    )
    assert cli_mod.main(["-c", str(config), "check"]) == 0
    return tmp_path


def _lockfile(root) -> str:
    return str(root / ".refdes" / "citations.yaml")


def _corrupt(root, shape: str) -> str:
    with open(_lockfile(root), "w", encoding="utf-8") as fh:
        fh.write(SHAPES[shape])
    with open(_lockfile(root), "rb") as fh:
        return fh.read()


@pytest.mark.parametrize("shape", SHAPE_IDS)
@pytest.mark.parametrize("command", ["check", "fetch"])
def test_a_corrupt_lockfile_is_a_diagnostic_not_a_traceback(project, shape, command, capsys, monkeypatch):
    """Each shape, at both readers F5 names: a diagnostic naming the file, a
    non-zero code, and a traceback-free run."""
    _corrupt(project, shape)
    fetched: list[str] = []
    monkeypatch.setattr(
        citations_mod, "fetch_bytes", lambda url, timeout=30.0: fetched.append(url) or b""
    )

    status = cli_mod.main(["-c", str(project / "refdes-project.yaml"), command])
    captured = capsys.readouterr()

    assert status != 0, f"{shape}/{command} exited 0 on a lockfile it cannot read"
    assert "Traceback" not in captured.err, captured.err
    assert "Traceback" not in captured.out, captured.out
    assert citations_mod.LOCKFILE in captured.err, captured.err
    assert not fetched, f"{shape}: {command} went to the network anyway"


@pytest.mark.parametrize("shape", SHAPE_IDS)
@pytest.mark.parametrize(
    "command",
    [("check",), ("build",), ("fetch",), ("fetch", "--update")],
)
def test_a_corrupt_lockfile_is_left_byte_identical(project, shape, command, monkeypatch):
    """The property that makes refusing worth refusing: a lockfile only a person
    can fix survives every run of the tool, byte for byte.

    `fetch --update` is the command that did lose pins on main -- it rewrote the
    whole lockfile from the record it had just fetched, so every pin it could
    not read was replaced by a fresh one and the file came back looking sound."""
    before = _corrupt(project, shape)
    monkeypatch.setattr(citations_mod, "fetch_bytes", lambda url, timeout=30.0: b"")

    cli_mod.main(["-c", str(project / "refdes-project.yaml"), *command])

    with open(_lockfile(project), "rb") as fh:
        assert fh.read() == before, f"{shape}: {' '.join(command)} rewrote the corrupt lockfile"


def test_the_diagnostic_names_the_line_it_could(project, capsys):
    """Where the shape gives a line, the diagnostic leads with `file:line` -- the
    convention every other diagnostic in the tool follows, and the only thing
    that makes a lockfile with fifty records navigable."""
    _corrupt(project, "merge-markers")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert f"{citations_mod.LOCKFILE}:1 —" in err, err

    capsys.readouterr()
    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert f"{citations_mod.LOCKFILE}:2 —" in err, err


def test_one_corrupt_file_is_reported_once_per_run(project, capsys):
    """`build` reads the lockfile twice (calc `source()` values, then
    `verify`); `check --refresh` a third time. One file with one problem must
    not read as three."""
    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert err.count(f"ERROR   {citations_mod.LOCKFILE}:") == 1, err


def test_check_does_not_also_call_every_citation_unpinned(project, capsys):
    """The reason this is an error and not a shrug: with the pins unreadable,
    reporting each citation `unpinned` would be a claim derived from a file
    nobody read, in enough volume to bury the one line that says so."""
    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert "has no fetched record" not in err, err


def test_a_merge_conflict_names_both_ways_out_and_what_they_cost(project, capsys):
    """The remedy for conflict markers has to be the merge's, not the generic
    one: which side wins changes which pins survive, and re-pinning is not free
    (refdes sends no conditional request, so it re-downloads)."""
    _corrupt(project, "merge-markers")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert "unresolved merge conflict" in err, err
    assert "`git checkout --ours .refdes/citations.yaml`" in err, err
    assert "`refdes fetch --update`" in err, err
    assert "re-downloading each cited document" in err, err


def test_every_shape_says_how_to_get_the_pins_back(project, capsys):
    """The generic remedy, on every shape but the merge's own: the file is
    committed, so `git checkout` restores the pins exactly."""
    for shape in SHAPE_IDS:
        if shape == "merge-markers":
            continue
        _corrupt(project, shape)
        assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1, shape
        err = capsys.readouterr().err
        assert f"`git checkout -- {citations_mod.LOCKFILE}`" in err, (shape, err)
        assert "downloads every cited document again" in err, (shape, err)


def test_fetch_exits_one_like_its_other_refusals(project, capsys):
    """`fetch`'s three documented refusals are exit 1, and this is a fourth of
    the same kind -- the project's state is unusable, which is not the
    configuration error the exit-2 rows name."""
    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "fetch"]) == 1


def test_a_repeated_key_says_which_block_loses_it(project, capsys):
    """The whole reason this shape is reported at all: nothing downstream can
    see the repeat, because loading is where it is lost. So the message has to
    carry what the loader threw away -- both lines, and which one wins."""
    _corrupt(project, "duplicate-record")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert f"duplicate key '{CITE}' in one mapping (lines 2 and 7)" in err, err
    assert "the block on line 2 is dropped for the one on line 7" in err, err
    assert "which of them was the pin" in err, err


def test_a_repeated_key_that_agrees_with_itself_says_nothing_is_lost(project, capsys):
    """The other half of the same comparison. A repeat of one block is still a
    mistake, but calling it a dropped record would be the one wrong thing in a
    message whose job is to be believed."""
    _corrupt(project, "duplicate-record-identical")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert "both blocks read the same, so nothing is lost here" in err, err
    assert "is dropped for" not in err, err


def test_a_repeated_key_on_one_line_does_not_report_two_lines(project, capsys):
    """A flow mapping puts both occurrences on one line, and "(lines 1 and 1)"
    reads like a bug in the diagnostic rather than in the file -- the same thing
    parse.py avoids for item front matter."""
    _corrupt(project, "duplicate-flow-one-line")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    err = capsys.readouterr().err
    assert "twice on line 1" in err, err
    assert "(lines 1 and 1)" not in err, err


def test_an_alias_cycle_is_walked_once_not_forever(project):
    """A YAML alias can make a node its own ancestor (`&a {b: *a}`). The
    duplicate walk has a visited set for exactly that: a report that hangs on a
    corrupt file is the same bug F5 is, wearing a different hat."""
    text = "citations: &a\n  self: *a\n"
    with open(_lockfile(project), "w", encoding="utf-8") as fh:
        fh.write(text)
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 1
    assert citations_mod._duplicate_key(text) is None


def test_build_under_keep_going_says_so_and_still_exits_zero(project, capsys):
    """`--keep-going` is documented as "Exit 0 even when there are errors", and
    an unreadable lockfile is an ordinary project error like any other -- so it
    takes the flag's contract, and says plainly on stderr that it failed. Pinned
    here because it is the one code path where a corrupt lockfile does not
    change the exit code."""
    _corrupt(project, "citations-list")
    assert cli_mod.main(
        ["-c", str(project / "refdes-project.yaml"), "build", "--keep-going"]
    ) == 0
    captured = capsys.readouterr()
    assert f"ERROR   {citations_mod.LOCKFILE}:" in captured.err, captured.err
    assert "1 items, 1 errors" in captured.out, captured.out


def test_a_sound_lockfile_still_loads_and_no_shape_false_positives(project):
    """The other direction, and the one that decides whether the check above is
    worth anything: every record `refdes fetch` itself writes must survive the
    reader, byte for byte through `lockfile_text`."""
    records = {
        CITE: {
            "sha256": SHA,
            "fetched": "2026-01-01T00:00:00Z",
            "kept_copy": False,
            "bytes": 509,
        },
        # Everything a real project accumulates, so the optional blocks are
        # exercised too: `sections` with its `sections_sha256`, and `values`.
        "datasheets/sheet.pdf": {
            "sha256": "a" * 64,
            "fetched": "2026-01-02T00:00:00Z",
            "kept_copy": True,
            "bytes": 42,
            "sections": {"Load Regulation": 3},
            "sections_sha256": "a" * 64,
            "values": {"k": {"reader": "csv", "value": "2"}},
        },
        # An all-digit digest: `lockfile_text` quotes it, and it must read back
        # as the string it is rather than as the integer YAML would otherwise
        # make of it.
        "https://www.example.com/zeros.pdf": {
            "sha256": "0" * 64,
            "fetched": "2026-01-03T00:00:00Z",
            "kept_copy": False,
            "bytes": 7,
        },
    }
    with open(_lockfile(project), "w", encoding="utf-8") as fh:
        fh.write(citations_mod.lockfile_text(records))

    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 0


def test_no_lockfile_at_all_is_not_corruption(project, capsys):
    """The distinction the refusal rests on: absent means this project has
    pinned nothing, which is ordinary and reported as an unpinned citation."""
    os.remove(_lockfile(project))
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "check"]) == 0
    out = capsys.readouterr()
    assert "Traceback" not in out.err
    assert citations_mod.LOCKFILE not in out.err


def test_audit_reports_the_lockfile_it_cannot_report_on(project, capsys):
    """`audit` says everything that has been made less visible, and its sections
    speak by omission: with the lockfile unreadable, `verify()` populates no
    `item.citations`, so the "Citations:" section prints nothing rather than
    printing a pin it does not have. A silently missing section is the thing an
    audit exists to prevent, so the error goes to stderr with the same rule the
    load errors already follow -- a diagnostic with no `item_id` is about a
    project-wide file, which no section of the report can speak for."""
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "audit"]) == 0
    sound = capsys.readouterr()
    assert "Citations:" in sound.out, sound.out

    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "audit"]) == 1
    corrupt = capsys.readouterr()
    assert f"ERROR   {citations_mod.LOCKFILE}:" in corrupt.err, corrupt.err
    assert "Citations:" not in corrupt.out, corrupt.out
    assert "Traceback" not in corrupt.err


def test_index_carries_the_lockfile_error_in_its_own_diagnostics(project, capsys):
    """`index` is the one command whose exit code is deliberately left alone
    (the VS Code extension discards the whole index on a non-zero exit), so
    this is where the diagnostic has to be: the JSON's `diagnostics` array,
    which the editor already reads."""
    _corrupt(project, "citations-list")
    assert cli_mod.main(["-c", str(project / "refdes-project.yaml"), "index"]) == 0
    payload = json.loads(capsys.readouterr().out)
    messages = [d["message"] for d in payload["diagnostics"]]
    assert any(citations_mod.LOCKFILE in m for m in messages), messages


def test_load_lockfile_raises_where_read_lockfile_reports(project):
    """The two halves, asserted directly. `load_lockfile` is what both writers
    of this file call, and it must raise rather than answer `{}` -- an empty
    mapping is what a project with no pins looks like, and a writer that read
    one would overwrite the pins it could not see."""
    _corrupt(project, "citations-list")
    from refdes.schema import load_project

    built = load_project(config_path=str(project / "refdes-project.yaml"))
    with pytest.raises(citations_mod.LockfileError) as raised:
        citations_mod.load_lockfile(built)
    assert citations_mod.LOCKFILE in str(raised.value)
    assert "citations" in str(raised.value)