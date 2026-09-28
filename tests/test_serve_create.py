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
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      status: { type: enum, choices: [draft, approved] }
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
