"""The create service: `serve.edit.create_item` (docs/design/browser-editor.md,
Slice 3 -- creation).

Sabotage-shaped like the edit tests: every "no" is asserted as a result *and*
as a byte-identical tree -- a failed creation reserves nothing in the ledger
and writes nothing to `items/`. The identity proofs that matter: two creates
racing for the same prefix get different ids under the write lock; an explicit
id that collides is refused, never silently accepted; the id the preview
promises is the id the item gets; and amending a sealed log never touches the
sealed entry's bytes.
"""

from __future__ import annotations

import os
import threading
from datetime import date

import pytest
from conftest import write_project_config

from refdes import build as build_mod
from refdes import dates, parse
from refdes.schema import load_project
from refdes.serve import edit as edit_mod
from refdes.serve.edit import Created, Invalid, Refused, create_item

SCHEMA = """\
site:
  title: "Create test"
date_format: DD/MM/YYYY
id:
  width: 3
boards:
  board-a:
    label: "Board A"
link_types:
  amends: { inverse: amended_by, label: Amends }
  refines: { inverse: refined_by, label: Refines }
  governed_by: { inverse: governs, label: Governed by }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, approved] }
    links:
      refines: [requirement]
      governed_by: [requirement, decision]
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
  log:
    prefix: LOG
    append_only: true
    fields:
      date: { type: date, required: true }
      summary: { type: text, required: true }
    links:
      amends: [log]
"""

REQS = """\
# keep me: the create path must not eat this
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.   # trailing comment
  - id: REQ-002
    text: Nothing addresses this yet.
"""

DECS = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
"""

LOG = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    date: 07/02/2026
    summary: Started the rail work.
"""

NOTES_MD = """\
---
id: REQ-010
type: requirement
board: board-a
text: A markdown requirement.
---

Body prose before a rule.
---
id: REQ-011
type: requirement
board: board-a
text: A second markdown requirement.
---

Body prose after the fence.
"""


@pytest.fixture
def project_root(tmp_path):
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(REQS, encoding="utf-8", newline="\n")
    (items / "decs.yaml").write_text(DECS, encoding="utf-8", newline="\n")
    (items / "log.yaml").write_text(LOG, encoding="utf-8", newline="\n")
    (items / "notes.md").write_text(NOTES_MD, encoding="utf-8", newline="\n")
    return tmp_path


def read(path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def tree(root, *subdirs) -> dict[str, str]:
    import hashlib

    files = {}
    for sub in subdirs:
        base = os.path.join(str(root), sub)
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, str(root)).replace("\\", "/")
                with open(path, "rb") as fh:
                    files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def mint_keys(root):
    """Keys on disk for the fixture's items. `load_readonly` -- the load every
    create plans against -- never mints, and a link target with no key is a
    refusal by design, so the link tests that mean to *succeed* have to put
    keys there first, the way any writable command would."""
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project)
    from refdes import keys as keys_mod

    keys_mod.mint_missing(project, write=True)


def mint_and_seal(root):
    """One ordinary writable load: mints every key, then a writable build
    seals the clean log entry -- the state a real project reaches on its own."""
    config = str(root / "refdes-project.yaml")
    project = load_project(config_path=config)
    parse.load_items(project)
    from refdes import keys as keys_mod

    keys_mod.mint_missing(project, write=True)
    project = load_project(config_path=config)
    parse.load_items(project)
    build_mod.build(project, seal_write=True, reseal=False)


# ------------------------------------------------------------ the three shapes


def test_create_appends_to_a_yaml_list_file(project_root):
    path = project_root / "items" / "reqs.yaml"
    before = read(path)

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "A new rail."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(result, Created), result.message
    # REQ-010/011 live in notes.md; the high water is per prefix, not per file
    assert result.item_id == "REQ-012"

    after = read(path)
    # Pure append: every pre-existing byte, comments included, untouched.
    assert after.startswith(before)
    assert "id: REQ-012" in after and "key: " in after and "text: A new rail." in after
    # the id is ledger-reserved
    ledger = (project_root / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "REQ-012" in ledger


def test_create_appends_to_a_multi_item_markdown_file(project_root):
    path = project_root / "items" / "notes.md"
    before = read(path)

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "From the editor."},
            destination="items/notes.md",
        ),
    )
    assert isinstance(result, Created), result.message
    after = read(path)
    assert after.startswith(before)

    project = load_project(config_path=str(project_root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    new = project.item_by_id(result.item_id)
    assert new is not None and new.source_file.replace("\\", "/") == "items/notes.md"
    assert new.fields["text"] == "From the editor."


def test_create_writes_a_new_single_item_markdown_file(project_root):
    path = project_root / "items" / "decisions" / "power.md"
    before_tree = tree(project_root, "items")

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="decision", fields={"title": "Power budget."},
            destination="items/decisions/power.md",
        ),
    )
    assert isinstance(result, Created), result.message
    assert result.item_id == "DEC-002"
    text = read(path)
    assert text.startswith("---\nid: DEC-002\nkey: ")
    assert "type: decision" in text and "title: Power budget." in text
    # nothing else in items/ moved
    after_tree = tree(project_root, "items")
    assert set(after_tree) - set(before_tree) == {"items/decisions/power.md"}
    del after_tree["items/decisions/power.md"]
    assert after_tree == before_tree


# ------------------------------------------- the destination file's own defaults
#
# The item about to be created inherits the destination file's `defaults:`
# exactly as every item already in that file does. When that block declares a
# `prefix:`, the new item is numbered under it -- the series `refdes id` picks
# for the same file. The create path used to plan from the bare type prefix
# instead, so a file of `REQ-SYS-*` collected `REQ-001` (a warning from
# `refdes check` about an id already written *and burned*).

PREFIXED_REQS = """\
defaults:
  type: requirement
  prefix: REQ-SYS
  owner: J. Bin

items:
  - id: REQ-SYS-001
    text: The rail shall supply 3.3 V.
  - id: REQ-SYS-002
    text: Nothing addresses this yet.
"""

# A type whose `status` field declares a default, the way the bundled
# standard's types do -- the case where a created item's initial field set
# carries a value the destination file may already be supplying.
STATUS_SCHEMA = """\
site:
  title: "Destination defaults test"
date_format: DD/MM/YYYY
id:
  width: 3
types:
  requirement:
    prefix: REQ
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, active], default: draft }
"""

PREFIXED_MD = """\
---
defaults:
  type: requirement
  prefix: REQ-SYS
---

---
id: REQ-SYS-001
text: The rail shall supply 3.3 V.
---

---
id: REQ-SYS-002
text: Nothing addresses this yet.
---
"""


@pytest.fixture
def prefixed_root(tmp_path):
    """The bug report's repro, verbatim in shape: a list file whose
    `defaults.prefix` (REQ-SYS) is not the type's bare prefix (REQ)."""
    write_project_config(tmp_path, SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    (items / "reqs.yaml").write_text(PREFIXED_REQS, encoding="utf-8", newline="\n")
    (items / "notes.md").write_text(PREFIXED_MD, encoding="utf-8", newline="\n")
    return tmp_path


def test_create_uses_the_destination_files_prefix_not_the_bare_type_prefix(prefixed_root):
    """The regression, as the report states it: creating into a file whose
    `defaults.prefix` differs from the type's must produce `REQ-SYS-*`, and
    must not produce `REQ-*` at all."""
    result = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "A new rail."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(result, Created), result.message
    assert result.item_id == "REQ-SYS-003"

    after = read(prefixed_root / "items" / "reqs.yaml")
    assert "id: REQ-SYS-003" in after
    assert "REQ-001\n" not in after.replace("REQ-SYS-001", "").replace("REQ-SYS-002", "")

    # The wrong series is not merely absent from the file, it is not burned:
    # a REQ-001 here would outlive the mistake in .refdes/ids.yaml.
    ledger = (prefixed_root / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "REQ-SYS-003" in ledger
    assert not any(line.strip() == "- REQ-001" for line in ledger.splitlines())


def test_the_created_id_is_the_one_refdes_id_would_have_assigned(prefixed_root, tmp_path):
    """The guarantee, stated as an equality: the same file, filled the same
    way by `refdes id` and by the editor's create endpoint, ends up with the
    same id. Built as two projects rather than one assertion about a literal,
    so it keeps holding if the numbering ever moves."""
    from refdes import ids as ids_mod

    def fresh(root):
        root.mkdir(parents=True)
        write_project_config(root, SCHEMA)
        (root / "items").mkdir()
        (root / "items" / "reqs.yaml").write_text(
            PREFIXED_REQS, encoding="utf-8", newline="\n"
        )
        return root

    twin = fresh(tmp_path / "twin")
    with open(twin / "items" / "reqs.yaml", "a", encoding="utf-8", newline="\n") as fh:
        fh.write("  - text: A new rail.\n")
    project = load_and_parse(twin)
    allocated = ids_mod.allocate(project)
    assert [new_id for _item, new_id in allocated] == ["REQ-SYS-003"]

    created = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "A new rail."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(created, Created), created.message
    assert created.item_id == allocated[0][1]


def test_create_in_a_markdown_file_honours_its_first_block_prefix(prefixed_root):
    """A Markdown file declares the same file-wide `defaults:` as a list
    file, in its first front-matter block -- so an item appended to one is
    numbered from it too."""
    result = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "From the editor."},
            destination="items/notes.md",
        ),
    )
    assert isinstance(result, Created), result.message
    assert result.item_id == "REQ-SYS-003"
    assert "id: REQ-SYS-003" in read(prefixed_root / "items" / "notes.md")


def test_create_in_a_brand_new_file_numbers_from_the_type(prefixed_root):
    """A file that does not exist yet cannot declare a `defaults:` block, so
    there is nothing to inherit and the type's bare prefix is correct --
    the same answer `refdes id` gives an item in a file with no defaults.
    Not a silent fallback: it is the only answer available."""
    result = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "First in a new file."},
            destination="items/decisions/elsewhere.md",
        ),
    )
    assert isinstance(result, Created), result.message
    assert result.item_id == "REQ-001"  # the bare type prefix: nothing to inherit


def test_preview_shows_the_destination_files_prefix_too(prefixed_root):
    """`format_id` exists so "a previewed id and an allocated one can never
    be spelled differently". The prefix was the half of that promise the
    preview could not keep: it showed REQ-004 and saving wrote REQ-SYS-003."""
    preview = edit_mod.preview_creation(
        load_and_parse(prefixed_root), "requirement", destination="items/reqs.yaml"
    )
    assert preview["id"] == "REQ-SYS-003"

    created = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Promised id."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(created, Created)
    assert created.item_id == preview["id"]


def test_explicit_id_override_is_judged_against_the_destination_files_prefix(prefixed_root):
    """The override is checked against the prefix the item will actually be
    numbered under, and the refusal says where that prefix came from."""
    wrong = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Wrong series."},
            id="REQ-050", destination="items/reqs.yaml",
        ),
    )
    assert isinstance(wrong, Refused)
    assert "REQ-SYS" in wrong.reason and "defaults" in wrong.reason
    assert not (prefixed_root / ".refdes").exists()  # refused burns nothing

    ok = create_item(
        str(prefixed_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Right series."},
            id="REQ-SYS-050", destination="items/reqs.yaml",
        ),
    )
    assert isinstance(ok, Created) and ok.item_id == "REQ-SYS-050"


def test_a_field_the_destination_defaults_supply_is_not_written_onto_the_item(tmp_path):
    """The same "the create path never looked at the file" bug, in its
    second dress: a file whose `defaults.status` is `active` was collecting
    items stamped `status: draft`, one explicit line per item, each one
    overriding the file. The item inherits `active`; the line is gone."""
    write_project_config(tmp_path, STATUS_SCHEMA)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "reqs.yaml").write_text(
        "defaults: { type: requirement, status: active }\n"
        "items:\n"
        "  - id: REQ-001\n    text: The rail shall supply 3.3 V.\n",
        encoding="utf-8",
        newline="\n",
    )

    inherited = create_item(
        str(tmp_path),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Inherits active."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(inherited, Created), inherited.message
    # One `status:` in the file, and it is the defaults block's: the new
    # entry carries none of its own to override it with.
    assert read(tmp_path / "items" / "reqs.yaml").count("status:") == 1

    # An author-supplied value is still the author's: overriding the file is
    # what supplying one means.
    chosen = create_item(
        str(tmp_path),
        edit_mod.CreateRequest(
            who="t", type="requirement",
            fields={"text": "Explicitly draft.", "status": "draft"},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(chosen, Created), chosen.message
    project = load_and_parse(tmp_path)
    assert project.item_by_id(inherited.item_id).fields["status"] == "active"
    assert project.item_by_id(chosen.item_id).fields["status"] == "draft"


# ------------------------------------------------------------------- identity


def test_two_concurrent_creates_never_claim_the_same_id(project_root):
    """The write lock plus plan-under-the-lock: the second create plans
    against what the first committed, so the numbers differ and both are
    reserved."""
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(
            create_item(
                str(project_root),
                edit_mod.CreateRequest(
                    who="t", type="requirement", fields={"text": "Racy."},
                    destination="items/reqs.yaml",
                ),
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert len(results) == 2 and all(isinstance(r, Created) for r in results)
    ids_made = sorted(r.item_id for r in results)
    assert ids_made == ["REQ-012", "REQ-013"]
    ledger = (project_root / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "REQ-012" in ledger and "REQ-013" in ledger


def test_explicit_id_override_is_honoured_or_refused_not_renumbered(project_root):
    clash = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Clash."},
            id="REQ-001", destination="items/reqs.yaml",
        ),
    )
    assert isinstance(clash, Refused) and not (project_root / ".refdes").exists()

    ok = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Chosen."},
            id="REQ-042", destination="items/reqs.yaml",
        ),
    )
    assert isinstance(ok, Created) and ok.item_id == "REQ-042"
    ledger = (project_root / ".refdes" / "ids.yaml").read_text(encoding="utf-8")
    assert "REQ-042" in ledger
    # and the next free number moves past the explicit one
    preview = edit_mod.preview_creation(
        load_and_parse(project_root), "requirement"
    )
    assert preview["id"] == "REQ-043"


def load_and_parse(root):
    project = load_project(config_path=str(root / "refdes-project.yaml"))
    parse.load_items(project, require_ids=False)
    return project


def test_preview_reserves_nothing_and_matches_the_created_id(project_root):
    ledger = project_root / ".refdes" / "ids.yaml"
    preview = edit_mod.preview_creation(load_and_parse(project_root), "requirement")
    assert preview["id"] == "REQ-012"
    assert not ledger.exists()  # a preview burns nothing

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Promised id."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(result, Created)
    assert result.item_id == preview["id"]  # the shown id is the gotten id


# ------------------------------------------------------------------- refusals


def test_invalid_field_leaves_nothing_behind(project_root):
    before = tree(project_root, "items", ".refdes")
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Bad enum.", "status": "bogus"},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(result, Invalid), result
    assert tree(project_root, "items", ".refdes") == before


def test_missing_required_field_is_blocked_by_the_schema(project_root):
    before = tree(project_root, "items", ".refdes")
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(who="t", type="requirement", fields={}, destination="items/reqs.yaml"),
    )
    assert isinstance(result, Invalid)
    assert tree(project_root, "items", ".refdes") == before


@pytest.mark.parametrize(
    ("destination", "fragment"),
    [
        ("../outside.md", "safe relative path"),
        ("items/../escape.md", "safe relative path"),
        ("items/new_list.yaml", "not a v1 destination"),
        ("items/notes.txt", ".md, .yaml, or .yml"),
    ],
)
def test_bad_destinations_refuse_and_write_nothing(project_root, destination, fragment):
    before = tree(project_root, "items", ".refdes")
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."}, destination=destination
        ),
    )
    assert isinstance(result, Refused), result
    assert fragment in result.reason
    assert tree(project_root, "items", ".refdes") == before


def test_unknown_type_and_unknown_field_are_refusals(project_root):
    before = tree(project_root, "items", ".refdes")
    r1 = create_item(
        str(project_root),
        edit_mod.CreateRequest(who="t", type="nope", fields={}, destination="items/reqs.yaml"),
    )
    assert isinstance(r1, Refused) and "no item type" in r1.reason
    r2 = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"bogus": 1}, destination="items/reqs.yaml"
        ),
    )
    assert isinstance(r2, Refused) and "does not declare a field" in r2.reason
    assert tree(project_root, "items", ".refdes") == before


# ------------------------------------------------------- logs and amendments


def test_new_log_gets_todays_date_in_the_project_format(project_root):
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="log", fields={"summary": "Chose the inductor."},
            destination="items/log.yaml",
        ),
    )
    assert isinstance(result, Created), result.message
    text = read(project_root / "items" / "log.yaml")
    today = dates.format_date(date.today(), "DD/MM/YYYY")
    assert f"date: {today}" in text
    # and it reparses as today under the project's format
    project = load_and_parse(project_root)
    entry = project.item_by_id(result.item_id)
    assert dates.parse_date(entry.fields["date"], project.date_format) == date.today()


def test_amending_a_sealed_log_never_touches_the_sealed_entry(project_root):
    mint_and_seal(project_root)
    sealed_project = load_and_parse(project_root)
    from refdes import seal as seal_mod

    sealed = sealed_project.item_by_id("LOG-001")
    assert sealed is not None and seal_mod.is_sealed(sealed_project, sealed)
    sealed_key = sealed.key
    path = project_root / "items" / "log.yaml"
    before = read(path)

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="log", fields={"summary": "Correction to the rail note."},
            destination="items/log.yaml", amends="LOG-001",
        ),
    )
    assert isinstance(result, Created), result.message
    after = read(path)
    # the sealed entry's bytes are exactly what they were; the correction is
    # pure creation appended after them
    assert after.startswith(before)
    assert f"amends: [LOG-001@{sealed_key}]" in after

    project = load_and_parse(project_root)
    entry = project.item_by_id(result.item_id)
    assert not seal_mod.is_sealed(project, entry)


def test_amends_requires_the_verb_and_a_keyed_target(project_root):
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", amends="LOG-001",
        ),
    )
    assert isinstance(r, Refused) and "does not declare an amends link" in r.reason
    assert tree(project_root, "items", ".refdes") == before


# ------------------------------------------------------- links at creation
#
# The other half of what the create form could not do (in-prog-logs/
# user-sim-release-gate-run1.md, F1): it could write an item's scalar shell and
# nothing else, so "a requirement that refines REQ-001" was a create plus one
# `add_link` edit per link. `CreateRequest.links` is `amends:` generalised to
# any verb the type declares -- same locked resolution, same
# `DISPLAY-ID@key` text, same single write. Every "no" below is asserted as a
# result *and* as a byte-identical tree: a link that will not resolve refuses
# the whole creation, so an item never lands with half the links it asked for.

KEYLESS = """\
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-090
    text: A requirement whose key was never minted.
"""


def test_a_declared_link_is_written_resolved_at_creation(project_root):
    mint_keys(project_root)
    target_key = load_and_parse(project_root).item_by_id("REQ-001").key
    assert target_key
    path = project_root / "items" / "reqs.yaml"
    before = read(path)

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Narrows the rail."},
            destination="items/reqs.yaml", links={"refines": ["REQ-001"]},
        ),
    )
    assert isinstance(result, Created), result.message
    after = read(path)
    # still one write, still a pure append: the link is in the first bytes
    assert after.startswith(before)
    assert f"refines: [REQ-001@{target_key}]" in after

    project = load_and_parse(project_root)
    new = project.item_by_id(result.item_id)
    assert new.links["refines"] == [f"REQ-001@{target_key}"]
    build_mod.resolve_links(project)
    assert new.resolved_links["refines"] == ["REQ-001"]


def test_a_multi_target_verb_is_one_flow_sequence_line(project_root):
    """The shape the standard's own items write -- `addresses: [A@k, B@k]` --
    one line per verb, targets in the order they were asked for."""
    mint_keys(project_root)
    project = load_and_parse(project_root)
    k_req = project.item_by_id("REQ-002").key
    k_dec = project.item_by_id("DEC-001").key

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Governed from two places."},
            destination="items/reqs.yaml", links={"governed_by": ["REQ-002", "DEC-001"]},
        ),
    )
    assert isinstance(result, Created), result.message
    text = read(project_root / "items" / "reqs.yaml")
    assert f"governed_by: [REQ-002@{k_req}, DEC-001@{k_dec}]" in text
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("governed_by:")]
    assert len(lines) == 1

    after = load_and_parse(project_root)
    build_mod.resolve_links(after)
    new = after.item_by_id(result.item_id)
    assert new.resolved_links["governed_by"] == ["REQ-002", "DEC-001"]


@pytest.mark.parametrize("destination", ["items/notes.md", "items/nested/more.md"])
def test_links_reach_every_destination_shape(project_root, destination):
    """`link_lines` is appended to the item's own lines, so the append-md and
    new-md shapes need nothing special -- asserted rather than assumed."""
    mint_keys(project_root)
    target_key = load_and_parse(project_root).item_by_id("REQ-001").key
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Linked in markdown."},
            destination=destination, links={"refines": ["REQ-001"]},
        ),
    )
    assert isinstance(result, Created), result.message
    assert f"refines: [REQ-001@{target_key}]" in read(result.path)
    new = load_and_parse(project_root).item_by_id(result.item_id)
    assert new.links["refines"] == [f"REQ-001@{target_key}"]


def test_a_request_that_supplies_no_links_writes_no_link_lines(project_root):
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Plain as before."},
            destination="items/reqs.yaml",
        ),
    )
    assert isinstance(result, Created), result.message
    text = read(project_root / "items" / "reqs.yaml")
    for verb in ("refines", "governed_by", "amends"):
        assert verb not in text


def test_a_verb_the_type_does_not_declare_is_refused(project_root):
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"verifies": ["REQ-001"]},
        ),
    )
    assert isinstance(r, Refused)
    assert "does not declare the link 'verifies'" in r.reason
    assert "refines, governed_by" in r.reason or "governed_by, refines" in r.reason
    assert tree(project_root, "items", ".refdes") == before


def test_a_target_of_the_wrong_allowed_type_names_the_types(project_root):
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"refines": ["DEC-001"]},
        ),
    )
    assert isinstance(r, Refused)
    assert "'refines' accepts targets of type requirement" in r.reason
    assert "DEC-001 is a decision" in r.reason
    assert tree(project_root, "items", ".refdes") == before


def test_a_target_that_is_not_in_the_project_is_refused(project_root):
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"refines": ["REQ-999"]},
        ),
    )
    assert isinstance(r, Refused) and "no item 'REQ-999'" in r.reason
    assert tree(project_root, "items", ".refdes") == before


def test_a_target_carrying_no_key_is_refused_the_way_amends_refuses_it(project_root):
    """A bare id would name the target but drop the identity the link is for,
    which is `_amends_line`'s refusal and now every verb's. The other items
    are keyed first, so the refusal can only be about REQ-090."""
    mint_keys(project_root)
    (project_root / "items" / "keyless.yaml").write_text(KEYLESS, encoding="utf-8", newline="\n")
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"refines": ["REQ-090"]},
        ),
    )
    assert isinstance(r, Refused) and "REQ-090 carries no artifact key" in r.reason
    assert tree(project_root, "items", ".refdes") == before


def test_a_composite_the_client_resolved_is_re_derived_not_copied(project_root):
    """The client may name a target by composite, but what lands on disk is
    `composite_for`'s own text, decided under the lock."""
    mint_keys(project_root)
    project = load_and_parse(project_root)
    target = project.item_by_id("REQ-001")
    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "Named by composite."},
            destination="items/reqs.yaml", links={"refines": [f"REQ-001@{target.key}"]},
        ),
    )
    assert isinstance(result, Created), result.message
    assert f"refines: [REQ-001@{target.key}]" in read(project_root / "items" / "reqs.yaml")


def test_a_composite_naming_an_unknown_key_is_refused(project_root):
    """The key half is what resolves; a composite whose key names nothing is
    not rescued by its label half."""
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"refines": ["REQ-001@zzzzzzzzzzz"]},
        ),
    )
    assert isinstance(r, Refused) and "no item 'REQ-001@zzzzzzzzzzz'" in r.reason
    assert tree(project_root, "items", ".refdes") == before


@pytest.mark.parametrize(
    "targets",
    [["REQ-001", "REQ-001"], ["REQ-001", "REQ-001@{key}"], ["{key}", "REQ-001"]],
)
def test_the_same_target_named_twice_is_refused(project_root, targets):
    """One creation links each target once. The three spellings of the same
    target are the point: the duplicate is caught on what it *resolves to*,
    not on the text sent, which is the same rule that makes a client-supplied
    composite get re-derived rather than copied."""
    mint_keys(project_root)
    key = load_and_parse(project_root).item_by_id("REQ-001").key
    refs = [t.format(key=key) for t in targets]
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links={"refines": refs},
        ),
    )
    assert isinstance(r, Refused) and "names REQ-001 twice" in r.reason
    assert tree(project_root, "items", ".refdes") == before


@pytest.mark.parametrize(
    "links",
    ["REQ-001", {"refines": "REQ-001"}, {"refines": []}, {"refines": [None]}, {"": ["REQ-001"]}],
)
def test_a_malformed_links_value_is_refused(project_root, links):
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="requirement", fields={"text": "X."},
            destination="items/reqs.yaml", links=links,
        ),
    )
    assert isinstance(r, Refused), r.message
    assert tree(project_root, "items", ".refdes") == before


def test_amends_requested_as_amends_and_again_in_links_is_refused(project_root):
    """One creation writes each verb once; two spellings of the same request
    is a client bug, not two lines of front matter."""
    mint_keys(project_root)
    before = tree(project_root, "items", ".refdes")
    r = create_item(
        str(project_root),
        edit_mod.CreateRequest(
            who="t", type="log", fields={"summary": "Correction."},
            destination="items/log.yaml", amends="LOG-001",
            links={"amends": ["LOG-001"]},
        ),
    )
    assert isinstance(r, Refused) and "twice" in r.reason
    assert tree(project_root, "items", ".refdes") == before


# -------------------------------------------------------------- destination


def test_destination_is_suggested_from_the_type_and_overridable(project_root):
    project = load_and_parse(project_root)
    assert edit_mod.suggest_destination(project, "decision") == "items/decs.yaml"
    # a type with no items yet suggests a new single-item Markdown file
    assert edit_mod.suggest_destination(project, "log") == "items/log.yaml"

    result = create_item(
        str(project_root),
        edit_mod.CreateRequest(who="t", type="decision", fields={"title": "Suggested spot."}),
    )
    assert isinstance(result, Created), result.message
    assert result.path.replace("\\", "/").endswith("items/decs.yaml")


# ---------------------------------------------------------------- HTTP face

from serve_support import Client, snapshot_tree  # noqa: E402

from refdes.serve.server import EditorApp  # noqa: E402


@pytest.fixture
def served(project_root):
    app = EditorApp(str(project_root / "refdes-project.yaml"), poll_interval=60)
    app.start()
    try:
        yield app, Client(app), project_root
    finally:
        app.stop()


def test_http_schema_preview_and_create_round_trip(served):
    _app, client, root = served
    status, schema = client.api_get("/api/create/schema")
    assert status == 200
    by_name = {t["name"]: t for t in schema["types"]}
    assert {"requirement", "decision", "log"} <= set(by_name)
    assert by_name["log"]["append_only"] and by_name["log"]["amends"]
    assert by_name["requirement"]["fields"]["text"]["required"]
    assert schema["date_format"] == "DD/MM/YYYY"

    status, prev = client.api_get("/api/create/preview?type=requirement")
    assert status == 200 and prev["id"] == "REQ-012"
    assert prev["destination"] in ("items/notes.md", "items/reqs.yaml")
    ledger = root / ".refdes" / "ids.yaml"
    assert not ledger.exists()  # a preview reserves nothing

    status, made = client.api_post(
        "/api/items/create",
        {"type": "requirement", "fields": {"text": "Via HTTP."}, "destination": "items/reqs.yaml"},
    )
    assert status == 200 and made["kind"] == "created"
    assert made["id"] == "REQ-012" and len(made["key"]) == 11
    assert "REQ-012" in ledger.read_text(encoding="utf-8")


def test_http_refusals_carry_reasons_and_write_nothing(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, refused = client.api_post(
        "/api/items/create",
        {"type": "nope", "fields": {}},
    )
    assert status == 422 and refused["kind"] == "refused"
    status, invalid = client.api_post(
        "/api/items/create",
        {"type": "requirement", "fields": {"status": "bogus"}, "destination": "items/reqs.yaml"},
    )
    assert status == 422 and invalid["kind"] == "invalid"
    status, bad = client.api_post("/api/items/create", {"fields": {}})
    assert status == 400
    after = snapshot_tree(root)
    after.pop(".refdes/schema.json", None)
    before.pop(".refdes/schema.json", None)
    assert after == before


def test_http_create_with_links_writes_resolved_composites(served):
    _app, client, root = served
    mint_keys(root)
    key = load_and_parse(root).item_by_id("REQ-001").key
    status, made = client.api_post(
        "/api/items/create",
        {
            "type": "requirement",
            "fields": {"text": "Via HTTP, with links."},
            "destination": "items/reqs.yaml",
            "links": {"refines": ["REQ-001"], "governed_by": ["REQ-002", "DEC-001"]},
        },
    )
    assert status == 200 and made["kind"] == "created", made
    text = (root / "items" / "reqs.yaml").read_text(encoding="utf-8")
    assert f"refines: [REQ-001@{key}]" in text
    assert "governed_by: [REQ-002@" in text and "DEC-001@" in text


def test_http_create_refuses_an_undeclared_verb_with_a_reason(served):
    _app, client, root = served
    before = snapshot_tree(root)
    status, refused = client.api_post(
        "/api/items/create",
        {
            "type": "requirement",
            "fields": {"text": "Nope."},
            "destination": "items/reqs.yaml",
            "links": {"verifies": ["REQ-001"]},
        },
    )
    assert status == 422 and refused["kind"] == "refused"
    assert "does not declare the link 'verifies'" in refused["reason"]
    after = snapshot_tree(root)
    after.pop(".refdes/schema.json", None)
    before.pop(".refdes/schema.json", None)
    assert after == before


@pytest.mark.parametrize(
    "links",
    ["REQ-001", {"refines": "REQ-001"}, {"refines": []}, {"refines": [3]}, {"refines": [""]}],
)
def test_http_create_rejects_a_malformed_links_field(served, links):
    """Shape is a 400 here, the same split as `fields`: what the verb means
    and whether the target resolves is the service's 422 to give."""
    _app, client, root = served
    before = snapshot_tree(root)
    status, payload = client.api_post(
        "/api/items/create",
        {"type": "requirement", "fields": {"text": "X."}, "links": links},
    )
    assert status == 400, payload
    after = snapshot_tree(root)
    after.pop(".refdes/schema.json", None)
    before.pop(".refdes/schema.json", None)
    assert after == before


def test_no_write_server_refuses_creation(project_root):
    before = snapshot_tree(project_root)
    app = EditorApp(str(project_root / "refdes-project.yaml"), poll_interval=60, read_only=True)
    app.start()
    try:
        _status, refused = Client(app).api_post(
            "/api/items/create",
            {"type": "requirement", "fields": {"text": "Nope."}, "destination": "items/reqs.yaml"},
        )
    finally:
        app.stop()
    assert refused["kind"] == "refused" and "--no-write" in refused["error"]
    assert snapshot_tree(project_root) == before
