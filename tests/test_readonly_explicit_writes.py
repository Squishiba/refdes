"""Read-only refusals for the explicit-write commands (user-sim run 4, F1).

`docs/cli-reference.md` claims that "no command in that state prints a Python
traceback -- each either degrades and says what it could not write, or
refuses". On main six commands reached a bare `textio.write_text` whose only
guard was that the filesystem would take it, so the claim was false for each
of them: `stub-tests`, `revise`, `calc-rewrite`, `standard upgrade`, `id`, and
`standard add-preset` / `remove-preset`.

Every test here is a chmod-based one, and every chmod-based one is skipped
where a permission bit cannot produce the condition -- on Windows, and when
running as root, which ignores the bit entirely. Both skips are the ones
`tests/test_citation_path_hygiene.py` uses for the same reason.

What each command does with the refusal is its own answer, and these pin the
answers rather than one rule:

- `revise` / `calc-rewrite` / `standard upgrade` roll the whole transaction
  back, exit 1, and name the file (the item files now refuse the same way the
  carried-forward seal always did -- which also meant two fixes *inside* the
  transaction: the rollback has to exist before the first write, and every
  restore has to compare before writing, or the rollback re-attempts the
  refusal the filesystem has just handed back).
- `stub-tests` cannot be all-or-nothing -- its files are independent and a
  written stub is the author's -- so it keeps what landed, names what was
  refused, and still exits 1.
- `id` allocates nothing for a file whose write-back was refused, and reports
  the ledger separately, because by then there is nothing to roll back.
- `standard add-preset` / `remove-preset` exit 2, the code they already use
  for "your config is not what you asked for it to be".

`keys adopt` and `keys restore` are deliberately *not* here: they still let
the refusal propagate and report the OS's own errno, without
`(read-only tree?)`. That asymmetry is documented rather than accidental --
see the destination table in `docs/cli-reference.md` -- and
`test_keys_adopt_still_reports_the_operating_system_s_own_reason` below is
what keeps the documentation honest about it.
"""

from __future__ import annotations

import os

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

# Windows has no POSIX permission bits, and root ignores them: `chmod a-w`
# produces a tree that is still fully writable to either, so the condition
# under test cannot be produced at all. The same skip shape as
# tests/test_citation_path_hygiene.py.
needs_posix_bits = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits: chmod a-w does not stop Windows (or "
    "root) from writing, so a read-only tree cannot be produced that way",
)


# ------------------------------------------------------------------ helpers


def _make_read_only(root) -> None:
    """`chmod -R a-w` over `root`, files and directories both -- a read-only
    *directory* still permits writing through to the files inside it, so
    flipping only the files' bits would not produce the condition. Always
    restored by the caller (`_make_writable`), or pytest cannot clean the
    temporary directory up afterwards.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o555)
    os.chmod(root, 0o555)


def _make_writable(root) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o644)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o755)
    os.chmod(root, 0o755)


def _make_one_dir_read_only(path) -> None:
    """Just one directory -- the partial shape, where the command's other
    writes still land and the report has to account for both halves."""
    for dirpath, dirnames, filenames in os.walk(path):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
        for name in dirnames:
            os.chmod(os.path.join(dirpath, name), 0o555)
    os.chmod(path, 0o555)


def _read(path) -> str:
    return open(path, encoding="utf-8").read()


def _all_text(paths) -> dict[str, str]:
    """Every file's bytes, so a test can assert nothing was half-applied."""
    return {str(p): _read(p) for p in paths if p.is_file()}


# --------------------------------------------------------------- fixtures

# A hardware@2 project, so `standard upgrade --to 3` has a real rename to
# write (`text:` -> `body:`, the field-unification migration).
V2_CONFIG = "site: { title: T, out: _site }\nstandard: { base: hardware, version: 2, presets: [] }\n"

V2_ITEMS = (
    "defaults: { type: requirement, prefix: REQ, status: active }\n"
    "items:\n"
    "  - id: REQ-001\n"
    "    title: Needs a verifying test\n"
    "    text: The unit shall operate from 9 V to 36 V.\n"
)


@pytest.fixture
def v2_project(tmp_path):
    write_project_config(tmp_path, V2_CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "req.yaml").write_text(V2_ITEMS, encoding="utf-8")
    return tmp_path


@pytest.fixture
def rename_project(tmp_path):
    """A project with a live prefix rename to apply through a mapping file --
    `revise`, `calc-rewrite` and `standard upgrade` all reach the same
    `write_rewrites` call, so one fixture serves all three."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  bound:\n"
        "    prefix: BND\n"
        "    fields:\n"
        "      text:  { type: text, required: true }\n"
        "      limit: { type: limit, required: true }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "i.yaml").write_text(
        "defaults:\n  type: bound\n  prefix: BND\n"
        "items:\n"
        "  - id: BND-001\n    text: Board power density\n    limit: \"<= 0.15 W/in^2\"\n",
        encoding="utf-8",
    )
    (tmp_path / "mapping.yaml").write_text("prefixes:\n  BND: LIM\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def pending_id_project(tmp_path):
    """One item with no `id:`, so `refdes id` has a real write-back to
    attempt rather than reporting that there is nothing to do."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    fields:\n"
        "      text: { type: text, required: true }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement }\nitems:\n  - text: Brand new.\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def preset_project(tmp_path):
    """`design-debate` already selected, so `remove-preset` has a real
    removal to do -- on a project without it, the command stops at a
    configuration error and never reaches its writes."""
    from refdes import scaffold as scaffold_mod

    scaffold_mod.init(str(tmp_path), presets=["design-debate"])
    return tmp_path


@pytest.fixture
def unselected_preset_project(tmp_path):
    """No preset selected, so `add-preset` has one to add. `design-debate` is
    the only preset the bundled standard offers, and asking for one it does
    not have is a configuration error (exit 2) that never reaches the write --
    so the fixture and the command have to agree on which half is under test."""
    from refdes import scaffold as scaffold_mod

    scaffold_mod.init(str(tmp_path))
    return tmp_path


# Two boards, so `stub-tests` has more than one group and one of them can be
# made unwritable while the others land. The report's partial shape: two of
# three files written, the third refused, and the summary of what landed is
# the only account of it.
TWO_BOARD_SCHEMA = """\
site: {title: "Stubs", out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
boards:
  power: {label: Power}
  thermal: {label: Thermal}
link_types:
  verifies: { inverse: verified_by, label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
    links: {}
  test:
    prefix: TST
    fields:
      title:  { type: text, required: true }
      status: { type: enum, choices: [planned, passing], default: planned }
      method: { type: text }
    verifying_statuses: [passing]
    links:
      verifies: [requirement]
"""

TWO_BOARD_ITEMS = {
    "power.md": """\
---
id: REQ-001
type: requirement
text: Power path.
board: power
---
""",
    "thermal.md": """\
---
id: REQ-002
type: requirement
text: Thermal path.
board: thermal
---
""",
    "mech.md": """\
---
id: REQ-003
type: requirement
text: Mechanical path.
board: power
---
""",
}


@pytest.fixture
def two_board_stub_project(tmp_path):
    write_project_config(tmp_path, TWO_BOARD_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    for name, text in TWO_BOARD_ITEMS.items():
        (items / name).write_text(text, encoding="utf-8")
    # `stub-tests` creates each board's directory itself, so a test that wants
    # to make one *unwritable* has to have it exist first -- which is also the
    # realistic shape (a board's items already live under `items/<board>/`).
    (items / "power").mkdir()
    return tmp_path


# ------------------------------------------------------------ revise / calc-rewrite
# (the same engine, so the same three defects: the item write must refuse,
#  the rollback must already exist, and no restore may re-attempt the refusal)


@needs_posix_bits
def test_revise_refuses_an_item_write_it_could_not_make(rename_project, capsys):
    """`revise` on a read-only `items/`: the rename's own file rewrite is the
    operation, not a side effect of it, so a refusal names the file, exits 1,
    and leaves the tree exactly as it was found."""
    config = str(rename_project / "refdes-project.yaml")
    before = _all_text(sorted((rename_project / "items").rglob("*.yaml")))
    _make_read_only(rename_project / "items")
    try:
        status = cli_mod.main(
            ["-c", config, "revise", str(rename_project / "mapping.yaml")]
        )
    finally:
        _make_writable(rename_project / "items")

    captured = capsys.readouterr()
    assert status == 1
    assert "refused:" in captured.err
    assert "cannot write items/i.yaml (read-only tree?)" in captured.err, captured.err
    assert "rolled back." in captured.err
    # The pre-rename id is still there: a rename that lands in some files and
    # not others is not a rename, so none of it landed.
    assert _all_text(sorted((rename_project / "items").rglob("*.yaml"))) == before


@needs_posix_bits
def test_revise_rolls_back_on_a_whole_tree_read_only(rename_project, capsys):
    """The whole-tree shape, which is the one that also makes the rollback
    itself unwritable. A rollback that re-attempts the write the filesystem
    has just refused raises the very `PermissionError` this is fixing -- so
    every restore compares before it writes, and the refusal survives its own
    cleanup as a report rather than as a traceback."""
    config = str(rename_project / "refdes-project.yaml")
    _make_read_only(rename_project)
    try:
        status = cli_mod.main(
            ["-c", config, "revise", str(rename_project / "mapping.yaml")]
        )
    finally:
        _make_writable(rename_project)

    captured = capsys.readouterr()
    assert status == 1
    assert "(read-only tree?)" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert "id: BND-001" in _read(rename_project / "items" / "i.yaml")


@needs_posix_bits
def test_revise_refuses_a_read_only_file_holding_only_a_reference(tmp_path, capsys):
    """The partial layout the whole-`items/` and one-read-only-subdirectory
    shapes cannot reach (user-sim run 5, finding B2).

    The one unwritable item file holds *no* id this rename moves: it is the
    file a `satisfies:` composite lives in, and the item being renamed sits
    in a perfectly writable sibling. So `apply()`'s own
    `write_rewrites(..., on_error=_refuse_item_write)` guard has nothing to
    refuse -- the rename's rewrite pass never plans a write for the read-only
    file at all, because the display half of a `DISPLAY@key` composite moves
    only in the post-rename `_refresh_display_halves` pass.

    That pass went through `links.expand_missing()`, which degrades on a
    refused write: it drops the planned rewrite for the file and reports
    nothing. The run therefore renamed REQ-001 -> BUD-001 in the writable
    file, left the composite naming the retired id, reported it as
    `1 prose mention(s) ... (a rename never edits prose)` -- it is a
    structured reference, misfiled as prose -- and exited 0.

    A rename that lands in some item files and not others is not a rename, so
    this refuses and rolls back exactly like every other layout.
    """
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n"
        "link_types:\n"
        "  satisfies: { inverse: satisfied_by, label: Satisfies }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    coverable: true\n"
        "    fields:\n"
        "      text: { type: text, required: true }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "    links:\n"
        "      satisfies: [requirement]\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "req.yaml").write_text(
        "defaults:\n  type: requirement\n  prefix: REQ\n"
        "items:\n  - id: REQ-001\n    text: Input voltage range.\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Buck topology.\n"
        "satisfies: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "mapping.yaml").write_text("prefixes:\n  REQ: BUD\n", encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")

    # A writable load first, so the keys are minted and the reference is
    # already composite -- the state this bug needs. Without it the rename
    # refuses earlier and for a different reason (a bare reference), which is
    # the shape `test_revise_refuses_an_item_write_it_could_not_make` covers.
    assert cli_mod.main(["-c", config, "check"]) == 0

    req, dec = items / "req.yaml", items / "dec.md"
    before = _all_text([req, dec])
    assert "REQ-001@" in _read(dec), "the composite reference this rename moves"

    os.chmod(dec, 0o444)
    try:
        status = cli_mod.main(["-c", config, "revise", str(tmp_path / "mapping.yaml")])
    finally:
        os.chmod(dec, 0o644)

    captured = capsys.readouterr()
    assert status == 1
    assert "refused:" in captured.err
    assert "cannot write items/dec.md (read-only tree?)" in captured.err, captured.err
    assert "rolled back." in captured.err
    # Never the shape the bug reported: a structured composite is not prose.
    assert "prose mention" not in captured.out
    # Rolled back, including the id the rename did land before the refresh
    # refused -- "changed 1 file(s)" with a live old reference is the failure.
    assert _all_text([req, dec]) == before
    assert "id: REQ-001" in _read(req)


@needs_posix_bits
def test_revise_dry_run_reports_the_refusal_a_read_only_file_will_cause(
    tmp_path, capsys
):
    """`--dry-run` copies the tree and runs the whole sequence on the copy,
    and `copytree` preserves the read-only bit -- so the simulation refuses
    exactly where the real run will. That makes the refusal a blocker to
    report rather than a clean preview of a rename that cannot land: the same
    shape, the same exit, one command earlier."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "id: { width: 3, ledger: .refdes/ids.yaml }\n"
        "link_types:\n"
        "  satisfies: { inverse: satisfied_by, label: Satisfies }\n"
        "types:\n"
        "  requirement:\n"
        "    prefix: REQ\n"
        "    coverable: true\n"
        "    fields:\n"
        "      text: { type: text, required: true }\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "    links:\n"
        "      satisfies: [requirement]\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "req.yaml").write_text(
        "defaults:\n  type: requirement\n  prefix: REQ\n"
        "items:\n  - id: REQ-001\n    text: Input voltage range.\n",
        encoding="utf-8",
    )
    (items / "dec.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: Buck topology.\n"
        "satisfies: [REQ-001]\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "mapping.yaml").write_text("prefixes:\n  REQ: BUD\n", encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    assert cli_mod.main(["-c", config, "check"]) == 0

    dec = items / "dec.md"
    before = _all_text([items / "req.yaml", dec])
    os.chmod(dec, 0o444)
    try:
        status = cli_mod.main(
            ["-c", config, "revise", "--dry-run", str(tmp_path / "mapping.yaml")]
        )
    finally:
        os.chmod(dec, 0o644)

    captured = capsys.readouterr()
    assert status == 1
    assert "cannot write items/dec.md (read-only tree?)" in captured.err, captured.err
    # A dry run touches nothing, on either side of the refusal.
    assert _all_text([items / "req.yaml", dec]) == before


@needs_posix_bits
def test_calc_rewrite_refuses_an_item_write_it_could_not_make(tmp_path, capsys):
    """`calc-rewrite` is the same transaction engine reached from another
    command, so a read-only `items/` must read the same way here -- including
    the rollback, which used to be able to raise on the way out."""
    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "types:\n"
        "  decision:\n"
        "    prefix: DEC\n"
        "    fields:\n"
        "      title: { type: text, required: true }\n"
        "      body: {}\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    dec = items / "dec.md"
    dec.write_text(
        "---\ntype: decision\nid: DEC-001\ntitle: Loss budget\n---\n\n"
        "```calc\nV = 12 V\nI = 0.5 A\nP : W = V * I  # conduction loss\n```\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")
    before = dec.read_text(encoding="utf-8")
    _make_read_only(items)
    try:
        status = cli_mod.main(["-c", config, "calc-rewrite"])
    finally:
        _make_writable(items)

    captured = capsys.readouterr()
    assert status == 1
    assert "cannot write items/dec.md (read-only tree?)" in captured.err, captured.err
    assert dec.read_text(encoding="utf-8") == before


@needs_posix_bits
def test_standard_upgrade_refuses_the_rename_it_could_not_write(v2_project, capsys):
    """`standard upgrade` runs the same engine with `mutate_config`, so its
    rollback has to put the version pin back too -- on a tree where that write
    is refused as well. Comparing before writing is what lets it: the pin was
    never bumped, because the refusal came before `mutate_config` ran."""
    config = str(v2_project / "refdes-project.yaml")
    _make_read_only(v2_project)
    try:
        status = cli_mod.main(["-c", config, "standard", "upgrade", "--to", "3"])
    finally:
        _make_writable(v2_project)

    captured = capsys.readouterr()
    assert status == 1
    assert "(read-only tree?)" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert "version: 2" in _read(v2_project / "refdes-project.yaml")
    assert "text:" in _read(v2_project / "items" / "req.yaml")


# ------------------------------------------------------------------ stub-tests


@needs_posix_bits
def test_stub_tests_refuses_the_file_it_could_not_write(two_board_stub_project, capsys):
    """The whole-`items/` shape: nothing lands, every file is named, and the
    exit is 1 -- not 0, because a run that left work undone is not a clean run.
    The wording is per-file rather than a count, because that is the shape
    every other explicit write uses and the one a log filter is written
    against."""
    config = str(two_board_stub_project / "refdes-project.yaml")
    _make_read_only(two_board_stub_project / "items")
    try:
        status = cli_mod.main(["-c", config, "stub-tests"])
    finally:
        _make_writable(two_board_stub_project / "items")

    captured = capsys.readouterr()
    assert status == 1
    assert "refused:" in captured.err
    for rel in ("items/power/stub-tests.md", "items/thermal/stub-tests.md"):
        assert f"cannot write {rel} (read-only tree?)" in captured.err, captured.err
    assert not list((two_board_stub_project / "items").rglob("stub-tests.md"))


@needs_posix_bits
def test_stub_tests_keeps_what_landed_and_names_what_did_not(
    two_board_stub_project, capsys
):
    """The partial shape the report called the sharper of the two commands:
    one board's directory read-only, the other writable. The file that was
    written is the author's from the moment it existed and is not taken back;
    the refused one is named; and both halves are on the screen, because the
    only account of a partial run used to be a traceback."""
    from refdes import stub_tests as stub_tests_mod

    config = str(two_board_stub_project / "refdes-project.yaml")
    plan = stub_tests_mod.generate(_built_project(config), dry_run=True)
    assert len(plan) == 2, plan
    blocked_rel = plan[0][0]
    landed_rel = plan[1][0]
    _make_one_dir_read_only((two_board_stub_project / blocked_rel).parent)

    try:
        status = cli_mod.main(["-c", config, "stub-tests"])
    finally:
        _make_writable(two_board_stub_project)

    captured = capsys.readouterr()
    assert status == 1
    assert f"cannot write {blocked_rel} (read-only tree?)" in captured.err, captured.err
    assert not (two_board_stub_project / blocked_rel).exists()
    # What did land is reported as landed, with the reminder that gives those
    # stubs ids -- the same lines the successful run prints.
    assert f"wrote 1 stub(s) to {landed_rel}" in captured.out, captured.out
    assert "wrote 1 stub test(s) across 1 file(s)" in captured.out
    assert "Run 'refdes id' to allocate ids for the new items." in captured.out
    assert "Traceback" not in captured.err + captured.out
    # And it is a real file, holding the one stub it covers.
    landed_ids = next(ids for rel, ids in plan if rel == landed_rel)
    text = _read(two_board_stub_project / landed_rel)
    for item_id in landed_ids:
        assert f"verifies: [{item_id}]" in text


@needs_posix_bits
def test_stub_tests_rerun_after_the_tree_is_writable_emits_no_duplicate(
    two_board_stub_project,
):
    """The recovery path the partial refusal has to leave open: re-running
    after the permission is restored picks up exactly the missed stubs.
    Deduplication is by declared link, so the ones already on disk are not
    emitted a second time -- without that property the report's own advice
    ("run it again") would double every stub."""
    from refdes import stub_tests as stub_tests_mod

    config = str(two_board_stub_project / "refdes-project.yaml")
    plan = stub_tests_mod.generate(_built_project(config), dry_run=True)
    assert len(plan) == 2, plan
    blocked_rel = plan[0][0]
    _make_one_dir_read_only((two_board_stub_project / blocked_rel).parent)
    try:
        with pytest.raises(stub_tests_mod.Refused):
            stub_tests_mod.generate(_built_project(config))
    finally:
        _make_writable(two_board_stub_project)

    second = stub_tests_mod.generate(_built_project(config))
    # Only the refused file's stubs are new.
    assert [rel for rel, _ids in second] == [blocked_rel], second
    for rel, ids in plan:
        text = _read(two_board_stub_project / rel)
        for item_id in ids:
            assert text.count(f"verifies: [{item_id}]") == 1, (rel, item_id)


def _built_project(config):
    """Load and build the project the way `cmd_stub_tests` does, so the plan
    and the real run see the same state -- deduplication reads declared links
    off both the id'd and the pending items."""
    from refdes import build as build_mod
    from refdes import parse as parse_mod
    from refdes.schema import load_project

    project = load_project(config_path=config)
    parse_mod.load_items(project, require_ids=False)
    build_mod.build(project, seal_write=False, reseal=False)
    return project


# ------------------------------------------------------------------------ id


@needs_posix_bits
def test_id_refuses_a_write_back_it_could_not_make(pending_id_project, capsys):
    """An id that never reached its source file is not allocated and its
    number stays free -- the same rule `id` already applied to an id it could
    not *place*, now applied to the filesystem's refusal. `allocated 0 id(s)`
    is the honest count."""
    config = str(pending_id_project / "refdes-project.yaml")
    before = _read(pending_id_project / "items" / "r.yaml")
    _make_read_only(pending_id_project / "items")
    try:
        status = cli_mod.main(["-c", config, "id"])
    finally:
        _make_writable(pending_id_project / "items")

    captured = capsys.readouterr()
    assert status == 1
    said = captured.err + captured.out
    assert "cannot write items/r.yaml (read-only tree?)" in said, said
    assert "none of them were allocated" in said
    assert "allocated 0 id(s)" in captured.out
    assert _read(pending_id_project / "items" / "r.yaml") == before
    # The ledger is still written -- `.refdes/` was writable -- but it records
    # nothing, which is the point: a number that was never allocated must not
    # be burned, or the next run would skip past it for no reason.
    ledger = _read(pending_id_project / ".refdes" / "ids.yaml")
    assert "REQ-001" not in ledger, ledger


@needs_posix_bits
def test_id_names_the_ledger_separately_when_only_it_is_refused(
    pending_id_project, capsys
):
    """The other half, and the reason it needs its own words: with `items/`
    writable the id *does* land, so there is nothing to roll back, but the
    ledger -- the only thing that stops a deleted item's number being handed
    out again -- does not. The report says which half is missing instead of
    claiming an allocation it could not record."""
    config = str(pending_id_project / "refdes-project.yaml")
    refdes = pending_id_project / ".refdes"
    refdes.mkdir(exist_ok=True)
    _make_read_only(refdes)
    try:
        status = cli_mod.main(["-c", config, "id"])
    finally:
        _make_writable(refdes)

    captured = capsys.readouterr()
    assert status == 1
    said = captured.err + captured.out
    assert "cannot write .refdes/ids.yaml (read-only tree?)" in said, said
    assert "Traceback" not in said


@needs_posix_bits
def test_id_on_a_whole_tree_read_only_names_both_halves(pending_id_project, capsys):
    """Both refusals on one run, and neither masks the other: the whole tree
    is read-only, so the item write and the ledger both fail, and each gets
    its own line -- different wording, because they are different states."""
    config = str(pending_id_project / "refdes-project.yaml")
    _make_read_only(pending_id_project)
    try:
        status = cli_mod.main(["-c", config, "id"])
    finally:
        _make_writable(pending_id_project)

    captured = capsys.readouterr()
    said = captured.err + captured.out
    assert status == 1
    assert "cannot write items/r.yaml (read-only tree?)" in said, said
    assert "cannot write .refdes/ids.yaml (read-only tree?)" in said, said
    assert "Traceback" not in said


# -------------------------------------------------------- standard add/remove-preset


@needs_posix_bits
def test_standard_add_preset_refuses_a_config_it_could_not_write(
    unselected_preset_project, capsys
):
    """Exit 2, not 1: the code these two commands already use for "your config
    is not what you asked for it to be" (an unknown preset, one not selected).
    A read-only config is one more way to arrive at the same place, and the
    config is left byte-identical so a re-run against a writable tree adds the
    preset for real."""
    config = str(unselected_preset_project / "refdes-project.yaml")
    before = _read(unselected_preset_project / "refdes-project.yaml")
    os.chmod(unselected_preset_project / "refdes-project.yaml", 0o444)
    try:
        status = cli_mod.main(
            ["-c", config, "standard", "add-preset", "design-debate"]
        )
    finally:
        os.chmod(unselected_preset_project / "refdes-project.yaml", 0o644)

    captured = capsys.readouterr()
    assert status == 2
    assert "cannot write refdes-project.yaml (read-only tree?)" in captured.err, captured.err
    assert "added preset" not in captured.out
    assert _read(unselected_preset_project / "refdes-project.yaml") == before


@needs_posix_bits
def test_standard_remove_preset_refuses_a_config_it_could_not_write(
    preset_project, capsys
):
    """The same for `remove-preset`, whose first write is a throwaway
    simulation copy beside the config. Refused *before* the try, so the
    `finally` that deletes that copy is not reached and there is no litter to
    clean up -- and, since nothing had changed either way, the same refusal
    answers for the real write that never ran."""
    config = str(preset_project / "refdes-project.yaml")
    before = _read(preset_project / "refdes-project.yaml")
    _make_read_only(preset_project / "refdes-project.yaml")
    try:
        status = cli_mod.main(
            ["-c", config, "standard", "remove-preset", "design-debate"]
        )
    finally:
        os.chmod(preset_project / "refdes-project.yaml", 0o644)

    captured = capsys.readouterr()
    assert status == 2
    assert "cannot write refdes-project.yaml (read-only tree?)" in captured.err, captured.err
    assert "Traceback" not in captured.err + captured.out
    assert _read(preset_project / "refdes-project.yaml") == before
    assert not (preset_project / "refdes-project.yaml.scratch").exists()


@needs_posix_bits
def test_standard_remove_preset_refuses_when_only_the_real_write_is(
    preset_project, capsys
):
    """The other half of `remove-preset`: a writable directory with a
    read-only *config file*. The simulation copy is written and deleted as
    usual, and the refusal lands on the write that would have changed
    something -- so this is the site the copy's own refusal stands in for,
    and it must say the same thing."""
    config = str(preset_project / "refdes-project.yaml")
    before = _read(preset_project / "refdes-project.yaml")
    os.chmod(preset_project / "refdes-project.yaml", 0o444)
    try:
        status = cli_mod.main(
            ["-c", config, "standard", "remove-preset", "design-debate"]
        )
    finally:
        os.chmod(preset_project / "refdes-project.yaml", 0o644)

    captured = capsys.readouterr()
    assert status == 2
    assert "cannot write refdes-project.yaml (read-only tree?)" in captured.err, captured.err
    assert _read(preset_project / "refdes-project.yaml") == before
    # The scratch copy is removed before the real write is attempted, so a
    # refusal here leaves no `.scratch` file behind.
    assert not (preset_project / "refdes-project.yaml.scratch").exists()


# ------------------------------------------- the documented exception (keys)


def test_keys_adopt_still_reports_the_operating_system_s_own_reason(tmp_path, capsys):
    """`keys adopt` and `keys restore` are the deliberate exception, and the
    destination table in `docs/cli-reference.md` now says so -- including that
    their message does *not* carry `(read-only tree?)`, so a CI filter written
    on that marker will miss exactly these two commands. This test is what
    keeps that row honest: if a future change gave them the marker, this fails
    and the documentation has to be corrected rather than left claiming a
    filter catches them.

    The refusal is injected rather than produced by chmod, so the assertion is
    about the *shape* of the message -- which is the thing documented -- and
    this runs identically on Windows and as root.
    """
    from refdes import adopt as adopt_mod

    write_project_config(
        tmp_path,
        "site: { title: T, out: _site }\n"
        "standard: { base: hardware, version: 3, presets: [] }\n",
    )
    items = tmp_path / "items"
    items.mkdir()
    (items / "r.yaml").write_text(
        "defaults: { type: requirement, prefix: REQ, status: active }\n"
        "items:\n  - id: REQ-001\n    title: T\n    body: B.\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")

    real_write = adopt_mod.revise.write_rewrites

    def _refuse(rewrites, on_error=None):
        raise PermissionError(13, "Permission denied", config)

    adopt_mod.revise.write_rewrites = _refuse
    try:
        status = cli_mod.main(["-c", config, "keys", "adopt"])
    finally:
        adopt_mod.revise.write_rewrites = real_write

    captured = capsys.readouterr()
    said = captured.err + captured.out
    assert status == 1
    assert "refused:" in said
    assert "Permission denied" in said, said
    # The documented asymmetry, asserted rather than assumed.
    assert "(read-only tree?)" not in said, said
