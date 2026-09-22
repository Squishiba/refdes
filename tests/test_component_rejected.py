"""Phase 4 (layout) tests for docs/design/candidate-parts.md §6.

Two of the six tests from §9's table, the ones this task owns:
`test_defaults_status_warning` (a `defaults:`-declared status no item in
the file actually carries is dead configuration, cached as a warning) and
`test_new_list_skeleton` (`refdes new <type> --list`, the list-file
skeleton printer). The other four -- `test_rejected_never_satisfies`,
`test_selects_rejected_component_warns`, `test_rejected_stays_on_parts_page`,
`test_hardware3_component_choices` -- are the Phase 1/3 work and land in a
separate change, so this file can be merged independently.
"""

from __future__ import annotations

import json
import os

import yaml
from conftest import write_project_config
from helpers import _build_at

from refdes import cli as cli_mod
from refdes import parse
from refdes import render
from refdes import scaffold as scaffold_mod
from refdes.schema import load_project


# ------------------------------------------------------------------- the warning


def test_defaults_status_warning(tmp_path):
    """A list file whose `defaults:` declares a `status` value no item in
    the file actually has (every entry's own value won) is dead
    configuration and warns. Everything is content-derived: nothing about
    the file's name or location is read, so renaming the file changes
    nothing the warning depends on (candidate parts §6.3, §6.1)."""
    scaffold_mod.init(str(tmp_path))
    power = tmp_path / "items" / "power"
    power.mkdir(parents=True)
    (power / "candidates.yaml").write_text(
        "defaults:\n"
        "  type: component\n"
        "  status: candidate\n"
        "\n"
        "items:\n"
        "  - id: CMP-PWR-001\n"
        "    title: The winner\n"
        "    status: selected\n"
        "  - id: CMP-PWR-002\n"
        "    title: The loser\n"
        "    status: rejected\n",
        encoding="utf-8",
    )
    project = load_project(start=str(tmp_path))
    parse.load_items(project)

    dead = [d for d in project.warnings if "dead configuration" in d.message]
    assert len(dead) == 1
    message = dead[0].message
    assert "'status: candidate'" in message
    assert "candidates.yaml" not in message  # not path-derived
    assert dead[0].file == "items/power/candidates.yaml"
    assert dead[0].line == 2  # the defaults: block's own first key line

    # Renaming the file changes nothing: same warning, same text.
    (power / "candidates.yaml").rename(power / "shortlist.yaml")
    renamed = load_project(start=str(tmp_path))
    parse.load_items(renamed)
    again = [d for d in renamed.warnings if "dead configuration" in d.message]
    assert len(again) == 1
    assert again[0].message == message

    # One item actually in the declared status: the default is doing its
    # job, so the same defaults: block warns nothing.
    (power / "matched.yaml").write_text(
        "defaults:\n"
        "  type: component\n"
        "  status: candidate\n"
        "\n"
        "items:\n"
        "  - id: CMP-PWR-003\n"
        "    title: Still a candidate\n",
        encoding="utf-8",
    )
    matched = load_project(start=str(tmp_path))
    parse.load_items(matched)
    matched_dead = [
        d for d in matched.warnings
        if d.file == "items/power/matched.yaml" and "dead configuration" in d.message
    ]
    assert not matched_dead


# ---------------------------------------------------------------- the --list flag


def test_new_list_skeleton(tmp_path, capsys):
    """`refdes new <type> --list` prints a list-file skeleton: a `defaults:`
    block carrying the items' shared type and the status field's default,
    then one empty entry. It prints the mapping form a list file must have
    (defaults: plus an items: key), writes nothing, and a type with no
    status field emits no status: line at all (candidate parts §6.4)."""
    scaffold_mod.init(str(tmp_path))
    config = str(tmp_path / "refdes-project.yaml")
    before = _tree(tmp_path)

    status = cli_mod.main(["-c", config, "new", "component", "--list"])
    assert status == 0
    out = capsys.readouterr().out
    assert "defaults:" in out
    assert "type: component" in out
    assert "status: candidate" in out
    assert "items:" in out
    assert "  - id:" in out
    assert "title:  # required" in out

    # The output is loadable as the mapping form parse_list_file requires --
    # redirecting it into place cannot produce a rejected list file.
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, dict)
    assert parsed["defaults"]["type"] == "component"
    assert parsed["defaults"]["status"] == "candidate"
    assert len(parsed["items"]) == 1
    entry = parsed["items"][0]
    assert entry["id"] is None
    assert "title" in entry
    assert "status" not in entry

    # A type with no status field (hardware@3's log) emits no status: line
    # at all and no dead default for a skeleton that can't use one.
    status = cli_mod.main(["-c", config, "new", "log", "--list"])
    assert status == 0
    out_log = capsys.readouterr().out
    assert "type: log" in out_log
    assert "date:  # required" in out_log
    assert "status" not in out_log

    # new writes nothing with or without --no-write, so composing the print
    # with a redirect is safe and --no-write keeps it side-effect-free.
    status = cli_mod.main(["--no-write", "-c", config, "new", "component", "--list"])
    assert status == 0
    assert capsys.readouterr().out == out
    assert _tree(tmp_path) == before


def _tree(root):
    return sorted(
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file()
    )


# ------------------------------------------------- the rejected status (Phase 1)
#
# The four tests from §9's `test_component_rejected.py` table that pin the
# `rejected` status itself -- coverage, the `selects:` disagreement, the parts
# page, and hardware@3's enum. They live here, alongside the two Phase 4
# tests above, so §9's third table lives in one file.

HARDWARE3 = """\
site: { title: Rejected, out: _site }
standard: { base: hardware, version: 3, presets: [] }
"""


def _hardware3(tmp_path, items_yaml):
    write_project_config(tmp_path, HARDWARE3)
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / "i.yaml").write_text(items_yaml, encoding="utf-8")
    return _build_at(tmp_path)


CANDIDATES_YAML = """\
items:
  - id: BND-PWR-001
    type: bound
    title: Input current
    status: active
    limit: ">= 3 A"
    body: The rail must source at least 3 A.
  - id: CMP-PWR-001
    type: component
    title: The chosen part
    part_number: MP1584EN-LF-Z
    status: selected
    satisfies: [BND-PWR-001]
  - id: CMP-PWR-002
    type: component
    title: The part that lost
    part_number: LM2596S-ADJ
    status: rejected
    satisfies: [BND-PWR-001]
"""


def test_rejected_never_satisfies(tmp_path):
    """`satisfying_statuses: [selected]` is the whole mechanism (§5.3): a
    `rejected` component that `satisfies:` a bound leaves it at `claimed`,
    while the selected one settles it. No new coverage code -- the existing
    four-stage model reads the status, and `rejected` simply is not in the
    allowed set."""
    project = _hardware3(tmp_path, CANDIDATES_YAML)
    assert not project.errors

    cov = project.coverage["BND-PWR-001"]
    assert cov.satisfied_by == ["CMP-PWR-001"]
    assert cov.claimed_by == ["CMP-PWR-002"]
    # The bound is settled by the selected part, so its stage is not
    # `claimed` here; the rejected part's own contribution is the pin.
    # Flip the winner off and the stage falls to `claimed`, never `satisfied`.
    (tmp_path / "items" / "i.yaml").write_text(
        CANDIDATES_YAML.replace("status: selected", "status: rejected"),
        encoding="utf-8",
    )
    flipped = _build_at(tmp_path)
    assert not flipped.errors
    assert flipped.coverage["BND-PWR-001"].satisfied_by == []
    assert flipped.coverage["BND-PWR-001"].claimed_by == ["CMP-PWR-001", "CMP-PWR-002"]
    assert flipped.coverage["BND-PWR-001"].stage == "claimed"


def test_selects_rejected_component_warns(tmp_path):
    """A decision `selects:` a `rejected` component: the existing
    `selects`/`selected` pair (§5.3) warns on the disagreement, and the
    warning is the whole response -- the engine never *derives* a status
    from the link, so the component stays `rejected`."""
    project = _hardware3(
        tmp_path,
        CANDIDATES_YAML
        + "  - id: DEC-PWR-001\n"
        "    type: decision\n"
        "    title: Pick the loser\n"
        "    status: accepted\n"
        "    selects: [CMP-PWR-002]\n",
    )
    found = [
        d for d in project.warnings
        if "selects CMP-PWR-002" in d.message and d.item_id == "DEC-PWR-001"
    ]
    assert len(found) == 1, [str(d) for d in project.warnings]
    assert "'rejected'" in found[0].message
    assert "'selected'" in found[0].message
    # A disagreement warns; it does not fail the build or move the status.
    assert not project.errors
    loser = next(i for i in project.items.values() if i.id == "CMP-PWR-002")
    assert loser.fields["status"] == "rejected"


def test_rejected_stays_on_parts_page(tmp_path):
    """`parts.html` indexes every part number the project wrote down (§5.5),
    and a rejected MPN is exactly the one a reviewer wants to find. The
    component keeps its row, and the preview payload the row's link carries
    shows its status."""
    project = _hardware3(tmp_path, CANDIDATES_YAML)
    out = render.render_site(project)
    html = open(os.path.join(out, "parts.html"), encoding="utf-8").read()

    assert "LM2596S-ADJ" in html
    assert 'data-ref="CMP-PWR-002"' in html

    payload = json.loads(
        html.split('<script id="preview-data" type="application/json">')[1]
        .split("</script>")[0]
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
    )
    fields = {f["name"]: f["value"] for f in payload["CMP-PWR-002"]["fields"]}
    assert fields["status"] == "rejected"


def test_hardware3_component_choices(tmp_path):
    """hardware@3's component status enum is `[candidate, selected, rejected,
    obsolete]` with default `candidate` (§5.6): declaration order is display
    order, the two comparison outcomes adjacent, retirement last."""
    project = _hardware3(tmp_path, CANDIDATES_YAML)
    field = project.types["component"].fields["status"]
    assert field.choices == ["candidate", "selected", "rejected", "obsolete"]
    assert field.default == "candidate"