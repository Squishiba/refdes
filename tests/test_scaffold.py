"""init, new, schema, presets -- and: refdes new, preset add/remove, preset-provided diagnostics.

Split out of the original monolithic tests/test_refdes.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest
from conftest import write_project_config
from helpers import REPO, _build_at_repo_schema

from refdes import cli as cli_mod
from refdes import parse, standards
from refdes import scaffold as scaffold_mod
from refdes.schema import SchemaError, load_project

# ------------------------------------------------ init, new, schema, presets

def test_latest_version_resolves_the_concrete_bundled_max():
    """Deliberately not a literal: this is the highest vN directory that
    actually ships, so hard-coding the number of the day just breaks on the
    next version bump without telling anyone anything."""
    bundled = [
        int(name[1:])
        for name in os.listdir(
            os.path.join(os.path.dirname(standards.__file__), "standards", "hardware")
        )
        if name.startswith("v")
    ]
    assert standards.latest_version("hardware") == max(bundled)
    assert standards.latest_version("hardware") >= 2


def test_available_presets_includes_design_debate():
    assert "design-debate" in standards.available_presets("hardware", 1)
    assert "design-debate" in standards.available_presets("hardware", 2)
    assert "design-debate" not in standards.available_presets("hardware", 3)


def _init_legacy(root, *, presets=()):
    """Pin old preset tests to the version that still offers it."""
    path = scaffold_mod.init(str(root))
    text = (root / "refdes-project.yaml").read_text(encoding="utf-8")
    (root / "refdes-project.yaml").write_text(
        text.replace("version: 3", "version: 2"), encoding="utf-8"
    )
    for preset in presets:
        scaffold_mod.add_preset(str(root), preset)
    return path


def test_preset_providers_maps_names_to_the_preset():
    types, link_types = standards.preset_providers("hardware", 1)
    assert types["debate"] == "design-debate"
    assert types["option"] == "design-debate"
    assert link_types["raises"] == "design-debate"
    assert link_types["resolved_by"] == "design-debate"


def test_init_writes_the_exact_documented_file(tmp_path):
    path = scaffold_mod.init(str(tmp_path))
    assert path == str(tmp_path / "refdes-project.yaml")
    text = open(path, encoding="utf-8").read()
    assert "types:" not in text
    assert "link_types:" not in text
    # line-anchored: `presets:` contains the substring `sets:`
    assert "\nsets:" not in text
    assert "standard:" in text
    assert "base: hardware" in text
    # The concrete integer, never the word "latest" -- and read from the
    # bundle rather than hard-coded, so a version bump doesn't fail here.
    assert f"version: {standards.latest_version('hardware')}" in text
    assert "latest" not in text
    assert "presets: []" in text

    # The file must actually load and resolve to a real, usable schema.
    project = load_project(config_path=path)
    assert "requirement" in project.types
    assert "log" in project.types


def test_init_standard_none_writes_the_escape_hatch(tmp_path):
    path = scaffold_mod.init(str(tmp_path), standard=None)
    text = open(path, encoding="utf-8").read()
    assert "standard: none" in text
    assert "base:" not in text


def test_init_with_preset_writes_it_into_the_list(tmp_path):
    path = _init_legacy(tmp_path, presets=["design-debate"])
    text = open(path, encoding="utf-8").read()
    assert "presets: [design-debate]" in text
    project = load_project(config_path=path)
    assert "debate" in project.types


def test_init_preset_with_standard_none_is_a_load_time_error(tmp_path):
    with pytest.raises(SchemaError, match="presets require a base standard"):
        scaffold_mod.init(str(tmp_path), standard=None, presets=["design-debate"])


def test_init_refuses_to_overwrite_an_existing_config(tmp_path):
    write_project_config(tmp_path, "site: {title: t, out: _site}\n")
    with pytest.raises(SchemaError, match="already exists"):
        scaffold_mod.init(str(tmp_path))


def test_init_writes_vscode_yaml_schema_association(tmp_path):
    scaffold_mod.init(str(tmp_path))
    settings = (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8")
    data = json.loads(settings)
    schema_keys = list(data["yaml.schemas"])
    assert len(schema_keys) == 1
    schema_key = schema_keys[0]
    assert data["yaml.schemas"][schema_key] == ["items/**/*.yaml"]
    # An absolute, this-project-only path -- not a bare relative one that two
    # different refdes projects would produce byte-identically (finding 9).
    assert os.path.isabs(schema_key)
    assert os.path.normpath(schema_key) == os.path.normpath(
        str(tmp_path / ".refdes" / "schema.json")
    )


def test_init_two_projects_get_disambiguated_schema_paths(tmp_path):
    """Finding 9: every generated .vscode/settings.json pointed at the same
    relative './.refdes/schema.json', so redhat.vscode-yaml -- which doesn't
    reliably scope a relative schema path to the workspace folder that
    declared it -- could apply one project's schema to another's files when
    both happened to be open in the same VS Code session (a multi-root
    workspace, or just switching folders without a full reload)."""
    proj_a = tmp_path / "a"
    proj_b = tmp_path / "b"
    scaffold_mod.init(str(proj_a))
    scaffold_mod.init(str(proj_b))

    settings_a = json.loads((proj_a / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    settings_b = json.loads((proj_b / ".vscode" / "settings.json").read_text(encoding="utf-8"))

    key_a = next(iter(settings_a["yaml.schemas"]))
    key_b = next(iter(settings_b["yaml.schemas"]))
    assert key_a != key_b, "two projects produced the identical, collision-prone schema key"


# ---------------- the consequences of that absolute path (user-sim run 2, BUG 3)
#
# The absolute path above is right; what was missing is everything that
# follows from it: the file it lands in is machine-specific, so it must not
# look committable; the docs must show what is actually emitted; and a
# settings file that was already there must not be skipped without a word.


def test_init_gitignores_the_vscode_settings_it_writes(tmp_path):
    scaffold_mod.init(str(tmp_path))
    assert ".vscode/settings.json" in (
        tmp_path / ".gitignore"
    ).read_text(encoding="utf-8").splitlines()


def test_init_vscode_settings_is_ignored_by_git(tmp_path):
    """The claim in git's own terms rather than as a substring of a file: a
    fresh `refdes init` leaves no committable file holding one machine's
    absolute path. Before the fix this probe exited 1 -- not ignored -- and
    `git status` listed `?? .vscode/`."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    proj = tmp_path / "proj"
    scaffold_mod.init(str(proj))
    subprocess.run([git, "init", "-q", str(proj)], check=True)

    probe = subprocess.run(
        [git, "-C", str(proj), "check-ignore", ".vscode/settings.json"],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, "git does not ignore .vscode/settings.json"
    assert probe.stdout.strip() == ".vscode/settings.json"

    status = subprocess.run(
        [git, "-C", str(proj), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    assert ".vscode" not in status.stdout


def _gitignore_patterns(path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_init_refdes_outputs_are_ignored_by_git(tmp_path):
    """F1 (remote-fetch-exercise.md §7): the docs promised `.refdes/copies/`
    and `.refdes/schema.json` were gitignored in three places and nothing in the
    product made them so -- `git add -A` in a fresh `init` project staged a 6 MB
    datasheet and a generated 1696-line schema. The claim in git's own terms
    rather than as a substring of a file: the `.refdes/` files a project is told
    to commit are still committable."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    proj = tmp_path / "proj"
    scaffold_mod.init(str(proj))
    subprocess.run([git, "init", "-q", str(proj)], check=True)
    (proj / ".refdes" / "copies").mkdir(parents=True)
    (proj / ".refdes" / "copies" / "deadbeef.pdf").write_bytes(b"%PDF-1.7\n")
    (proj / ".refdes" / "ids.yaml").write_text("next: 1\n", encoding="utf-8")
    # The coordination file a refdes write leaves behind. It is
    # created empty, so without an entry for it a project that saved once shows
    # an untracked `.refdes-write.lock` in `git status`.
    (proj / ".refdes-write.lock").write_bytes(b"")

    for ignored in (
        ".refdes/copies/deadbeef.pdf",
        ".refdes/schema.json",
        ".refdes-write.lock",
    ):
        probe = subprocess.run(
            [git, "-C", str(proj), "check-ignore", "-v", ignored],
            capture_output=True,
            text=True,
        )
        # `check-ignore -v` prints "<source>:<line>:<pattern>\t<pathname>"
        assert probe.returncode == 0, f"git does not ignore {ignored}"
        assert probe.stdout.split("\t")[1].strip() == ignored, probe.stdout

    # ...and the project's own record is still committable
    keep = subprocess.run(
        [git, "-C", str(proj), "check-ignore", ".refdes/ids.yaml"],
        capture_output=True,
        text=True,
    )
    assert keep.returncode == 1, "init's .gitignore entries swallowed .refdes/ids.yaml"


def test_init_gitignore_holds_when_the_project_is_one_directory_of_a_repo(tmp_path):
    """The same three files, checked in the layout a refdes project nested inside
    a larger repository lands in. The patterns carry no leading slash but do
    contain one away from their end, so git reads them relative to the directory
    holding the `.gitignore` -- which is what makes one spelling right for both
    layouts. Verified with `git check-ignore -v` in both.

    One path per `check-ignore` call on purpose: given several, git exits 0 if
    *any* of them is ignored, so a batch would report success for the two paths
    that were already covered and say nothing about a third that was not.
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    repo = tmp_path / "repo"
    proj = repo / "hardware" / "board-a"
    proj.mkdir(parents=True)
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    scaffold_mod.init(str(proj))
    (proj / ".refdes" / "copies").mkdir(parents=True)
    (proj / ".refdes" / "copies" / "deadbeef.pdf").write_bytes(b"%PDF-1.7\n")

    for rel in (
        "hardware/board-a/.refdes/copies/deadbeef.pdf",
        "hardware/board-a/.refdes/schema.json",
        "hardware/board-a/.refdes-write.lock",
    ):
        probe = subprocess.run(
            [git, "-C", str(repo), "check-ignore", "-v", rel],
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0, f"git does not ignore {rel}"
        # and it is this project's own .gitignore doing it, at the project's depth
        assert probe.stdout.startswith("hardware/board-a/.gitignore:"), probe.stdout


def test_init_ignores_the_files_not_the_surrounding_directories(tmp_path):
    """The exact set of patterns, which is the whole claim: each names one file
    or one subdirectory, never `.vscode/` or `.refdes/` as a whole. Both
    hold committable things -- this repo commits its own `.vscode/` and needs
    `.refdes/ids.yaml` and `.refdes/citations.yaml` in git, or two branches hand
    out the same ID or re-pin a datasheet without anyone noticing."""
    scaffold_mod.init(str(tmp_path))
    assert _gitignore_patterns(tmp_path / ".gitignore") == [
        ".vscode/settings.json",
        ".refdes/copies/",
        ".refdes/schema.json",
        ".refdes-write.lock",
    ]


def test_init_keeps_an_existing_gitignore_and_adds_the_entry_once(tmp_path):
    (tmp_path / ".gitignore").write_text("_site/\n.refdes/copies/\n", encoding="utf-8")
    scaffold_mod.init(str(tmp_path))
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("_site/\n.refdes/copies/\n")
    assert text.count(".vscode/settings.json") == 1
    # the project's own `.refdes/copies/` line is a position already taken, so
    # ours is not appended beside it
    assert text.count(".refdes/copies/") == 1
    assert ".refdes/schema.json" in text.splitlines()
    # the missing ones, each stated exactly once
    assert text.count(".refdes/schema.json") == 1
    assert text.count(".refdes-write.lock") == 1


def test_init_appends_with_the_existing_gitignore_line_ending(tmp_path):
    (tmp_path / ".gitignore").write_bytes(b"_site/\r\n")
    scaffold_mod.init(str(tmp_path))
    raw = (tmp_path / ".gitignore").read_bytes()
    assert b"\r\n\r\n# Written by `refdes init`" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "appended block grew an LF island"


@pytest.mark.parametrize(
    ("covering", "pattern"),
    [
        (".vscode/settings.json", ".vscode/settings.json"),
        ("/.vscode/settings.json", ".vscode/settings.json"),
        ("**/.vscode/settings.json", ".vscode/settings.json"),
        (".vscode", ".vscode/settings.json"),
        (".vscode/", ".vscode/settings.json"),
        ("/.vscode/", ".vscode/settings.json"),
        ("**/.vscode/", ".vscode/settings.json"),
        # an explicit negation is also the project having already decided:
        # git takes the last match, so appending ours would out-rank it
        ("!.vscode/settings.json", ".vscode/settings.json"),
        (".refdes/copies/", ".refdes/copies/"),
        ("/.refdes/copies/", ".refdes/copies/"),
        ("**/.refdes/copies/", ".refdes/copies/"),
        (".refdes", ".refdes/copies/"),
        (".refdes/", ".refdes/copies/"),
        (".refdes/", ".refdes/schema.json"),
        ("**/.refdes/", ".refdes/schema.json"),
        ("!.refdes/schema.json", ".refdes/schema.json"),
        (".refdes-write.lock", ".refdes-write.lock"),
        ("/.refdes-write.lock", ".refdes-write.lock"),
        ("**/.refdes-write.lock", ".refdes-write.lock"),
        ("!.refdes-write.lock", ".refdes-write.lock"),
    ],
)
def test_init_adds_no_block_for_a_pattern_the_project_already_addressed(
    tmp_path, covering, pattern
):
    (tmp_path / ".gitignore").write_text(f"{covering}\n", encoding="utf-8")
    scaffold_mod.init(str(tmp_path))
    patterns = _gitignore_patterns(tmp_path / ".gitignore")
    # no second line for a position already taken -- and when `covering` spells
    # it the same way, no duplicate of the project's own line either
    assert patterns.count(pattern) == (1 if covering == pattern else 0)
    assert patterns[0] == covering, "the project's own line moved or was rewritten"


def test_init_leaves_a_gitignore_that_addresses_everything_untouched(tmp_path):
    """All four already stated: nothing to append, so the file is byte-for-byte
    what the author had."""
    before = (
        ".refdes/copies/\n.refdes/schema.json\n.refdes-write.lock\n.vscode/settings.json\n"
    )
    (tmp_path / ".gitignore").write_text(before, encoding="utf-8")
    scaffold_mod.init(str(tmp_path))
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == before


def test_init_appends_nothing_on_a_second_init(tmp_path):
    """`init` refuses to overwrite an existing config, so a second run is what a
    re-init after deleting the config looks like -- and the append must not
    duplicate itself, for the lock file's block as much as for any other."""
    scaffold_mod.init(str(tmp_path))
    after_first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert after_first.count(".refdes-write.lock") == 1
    os.remove(tmp_path / "refdes-project.yaml")
    os.remove(tmp_path / ".vscode" / "settings.json")
    scaffold_mod.init(str(tmp_path))
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == after_first


def test_init_explains_the_serve_write_lock_it_ignores(tmp_path):
    """The block says why the file is not worth committing, because that is the
    whole decision: a per-machine coordination file with no content in it, and
    nothing in it a commit could carry to another clone. The comment is the
    contiguous run of `#` lines directly above its own pattern, so a reader who
    deletes the line knows which one it explained."""
    scaffold_mod.init(str(tmp_path))
    lines = [
        line for line in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    at = lines.index(".refdes-write.lock")
    above = lines[:at]
    start = len(above)
    while start and above[start - 1].startswith("#"):
        start -= 1
    comment = "\n".join(above[start:])

    assert comment.startswith("# Shared project write lock")
    assert "CLI and serve" in comment
    assert "per-machine" in comment


def test_init_adds_the_entry_for_an_unrelated_similar_pattern(tmp_path):
    """Guards the coverage check against matching on substring rather than
    on a whole pattern line."""
    (tmp_path / ".gitignore").write_text(".vscodeignore\n.refdescopies/\n", encoding="utf-8")
    scaffold_mod.init(str(tmp_path))
    assert ".vscode/settings.json" in _gitignore_patterns(tmp_path / ".gitignore")
    assert ".refdes/copies/" in _gitignore_patterns(tmp_path / ".gitignore")


def test_init_writes_no_vscode_entry_when_it_wrote_no_vscode_settings(tmp_path):
    """That entry exists because `init` wrote a machine-specific file. With
    nothing written there is nothing of ours to ignore -- but the `.refdes/`
    entries are wanted either way, since `build`/`check`/`fetch` write those
    files whatever happened here."""
    scaffold_mod.init(str(tmp_path), write_vscode_settings=False)
    assert not (tmp_path / ".vscode").exists()
    assert _gitignore_patterns(tmp_path / ".gitignore") == [
        ".refdes/copies/",
        ".refdes/schema.json",
        ".refdes-write.lock",
    ]


def test_cli_notes_an_existing_vscode_settings_file_instead_of_skipping_silently(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".vscode").mkdir()
    before = '{\n  // hand-written, and comments are legal here\n  "editor.formatOnSave": true\n}\n'
    (tmp_path / ".vscode" / "settings.json").write_text(before, encoding="utf-8")

    assert cli_mod.main(["init"]) == 0
    out = capsys.readouterr().out

    assert "note: .vscode/settings.json already exists; left it alone" in out
    # the write announcement is for the file init actually wrote
    assert "wrote .vscode/settings.json" not in out
    assert "yaml.schemas" in out and "schema completion" in out
    # the real absolute path, not a `<path>` placeholder: the line is
    # paste-ready into the file the note names. Normalised through abspath on
    # this side too, because init's path comes from os.getcwd() -- which on
    # Windows hands back the long form of an 8.3 temp directory.
    assert ".refdes/schema.json" in out
    assert os.path.abspath(str(tmp_path)).replace("\\", "/") in out
    assert "<path>" not in out

    # the file is byte-for-byte what it was. init does not merge into a file
    # it does not own -- .vscode/settings.json is JSONC, so a comment-
    # preserving merge is a parser rather than a patch, and a merge would
    # write a machine-specific path into a file the author may already track.
    assert (tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8") == before
    # and no .gitignore entry for that file, since init did not write it. The
    # `.refdes/` entries are still there: those files exist whatever happened
    # to the editor settings.
    assert ".vscode/settings.json" not in _gitignore_patterns(
        tmp_path / ".gitignore"
    )


def test_cli_prints_no_skip_note_when_it_wrote_the_settings_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["init"]) == 0
    assert "already exists" not in capsys.readouterr().out


def test_cli_announces_the_vscode_settings_file_it_wrote(tmp_path, monkeypatch, capsys):
    """`init` writes three things and used to name one of them (user-sim run 2,
    "Lower severity" list): `.vscode/settings.json` appeared with no word about
    it, so the only way to learn schema completion had just been wired up -- or
    that a machine-specific file had just been added to the tree -- was to list
    the directory. The skip is announced (BUG 3); the write has to be too. And
    the `.gitignore` is the third thing, so it is announced by what it now
    ignores -- not by the act of writing it, which would be a lie when a
    project's own `.gitignore` already covered the path.
    """
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["init"]) == 0
    out = capsys.readouterr().out

    assert (tmp_path / ".vscode" / "settings.json").is_file()
    assert [line for line in out.splitlines() if line.startswith("wrote ")] == [
        "wrote refdes-project.yaml",
        (
            "wrote .vscode/settings.json (gitignored -- the yaml.schemas path in it "
            "names one checkout)"
        ),
        (
            "wrote .gitignore (.vscode/settings.json, .refdes/copies/, "
            ".refdes/schema.json, .refdes-write.lock -- not yours to commit)"
        ),
    ]
    # the line says why the file is not worth committing, because that is the
    # other surprise it leaves behind: init also put it in .gitignore
    assert "gitignored" in out
    assert (tmp_path / ".gitignore").is_file()


def test_cli_announces_only_the_patterns_init_actually_added(tmp_path, monkeypatch, capsys):
    """The announcement follows what changed, not what init would have liked to
    write: a project that already ignored `.refdes/copies/` gets no line for it,
    and one whose `.gitignore` already covers everything gets no line at all
    (there is no third file to announce then)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(
        ".refdes/copies/\n.refdes/schema.json\n.refdes-write.lock\n", encoding="utf-8"
    )
    assert cli_mod.main(["init"]) == 0
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if "wrote .gitignore" in line] == [
        "wrote .gitignore (.vscode/settings.json -- not yours to commit)"
    ]


def test_cli_prints_no_gitignore_line_when_everything_was_already_ignored(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(
        ".refdes/\n.vscode/\n.refdes-write.lock\n", encoding="utf-8"
    )
    assert cli_mod.main(["init"]) == 0
    out = capsys.readouterr().out
    assert ".gitignore" not in out
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".refdes/\n.vscode/\n.refdes-write.lock\n"


def test_docs_show_the_absolute_schema_path_init_actually_emits():
    """docs/standard-library.md showed `"./.refdes/schema.json"` under "refdes
    init writes this for you" while the code emits an absolute path (user-sim
    run 2, BUG 3). Same gate as test_docs_examples.py runs on the generated
    type examples: the page must agree with what the tool does."""
    with open(os.path.join(REPO, "docs", "standard-library.md"), encoding="utf-8") as fh:
        doc = fh.read()

    blocks = [b for b in doc.split("```")[1:] if "yaml.schemas" in b]
    assert blocks, "docs/standard-library.md no longer shows a yaml.schemas example"
    lines = blocks[0].splitlines()
    if lines and lines[0].strip() in ("json", "jsonc"):
        lines = lines[1:]
    body = "\n".join(line for line in lines if not line.strip().startswith("//"))
    key = next(iter(json.loads(body)["yaml.schemas"]))

    assert key.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", key), (
        f"the documented example is not the absolute path init emits: {key!r}"
    )
    # and the page says why, rather than just differing: multi-root schema
    # resolution is the reason the code gives, and the gitignore the consequence
    assert "multi-root" in doc
    assert ".gitignore" in doc


def test_cli_init_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    status = cli_mod.main(["init"])
    assert status == 0
    assert (tmp_path / "refdes-project.yaml").is_file()
    assert (tmp_path / ".vscode" / "settings.json").is_file()
    out = capsys.readouterr().out
    assert f"standard: hardware@{standards.latest_version('hardware')}" in out


def test_cli_init_points_at_the_published_docs_site_not_a_repo_relative_path(
    tmp_path, monkeypatch, capsys
):
    """The candidate-parts pointer was `docs/parts.md#...`, a repo-relative
    path. `init` creates no docs/ directory, and the wheel ships no .md files
    at all, so that string named a file that did not exist for anyone who
    installed refdes -- on the very first thing the tool ever says (user-sim
    run 1, finding L1). It has to be the published site, which resolves for a
    checkout user and a wheel user alike."""
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["init"]) == 0
    out = capsys.readouterr().out

    assert not (tmp_path / "docs").exists(), (
        "if init ever started generating a docs/ directory, this test's premise "
        "-- that the pointer cannot be repo-relative -- would need revisiting"
    )
    assert "docs/parts.md" not in out
    assert (
        "https://squishiba.github.io/refdes/parts.html"
        "#candidate-parts-the-recommended-layout"
    ) in out


# --------------------------------------------------------------- refdes new


def test_new_item_text_required_field_no_default_is_a_placeholder():
    project = _build_at_repo_schema()
    spec = project.types["bound"]
    text = scaffold_mod.new_item_text("bound", spec)
    assert "type: bound" in text
    assert "limit:  # required -- limit" in text


def test_new_item_text_hints_a_required_body_when_the_type_has_no_other_content():
    """requirement's only content field is body:, reserved rather than a
    normal schema field, so it never appears in the fields: loop above --
    this is the hint that fills the gap."""
    project = _build_at_repo_schema()
    spec = project.types["requirement"]
    text = scaffold_mod.new_item_text("requirement", spec)
    assert "required: the content itself goes here." in text


def test_new_item_text_hints_an_optional_body_otherwise():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "optional body." in text


def test_new_item_text_field_with_default_is_uncommented_with_the_default():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "status: proposed  # choices:" in text


def test_new_item_text_optional_field_is_commented_out():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# date:  # date" in text


def test_new_item_text_required_when_field_notes_the_condition():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# rationale:" in text
    assert "required when status is 'rejected'" in text


def test_new_item_text_links_are_commented_out_with_target_hint():
    project = _build_at_repo_schema()
    spec = project.types["decision"]
    text = scaffold_mod.new_item_text("decision", spec)
    assert "# satisfies: []  # target: requirement" in text


def test_cli_new_unknown_type_reports_a_hint(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "new", "lgo"])
    assert status == 1
    err = capsys.readouterr().err
    assert "unknown type 'lgo'" in err
    assert "Did you mean 'log'?" in err


def test_cli_new_known_type_prints_scaffold(tmp_path, capsys):
    scaffold_mod.init(str(tmp_path))
    status = cli_mod.main(["-c", str(tmp_path / "refdes-project.yaml"), "new", "requirement"])
    assert status == 0
    out = capsys.readouterr().out
    assert "type: requirement" in out


# ------------------------------------------------------- preset add/remove


def test_add_preset_appends_to_the_list(tmp_path):
    _init_legacy(tmp_path)
    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes-project.yaml").read_text(encoding="utf-8")
    assert "presets: [design-debate]" in text


def test_add_preset_unknown_name_is_an_error(tmp_path):
    _init_legacy(tmp_path)
    with pytest.raises(SchemaError, match="does not exist"):
        scaffold_mod.add_preset(str(tmp_path), "nope-preset")


def test_add_preset_already_selected_is_an_error(tmp_path):
    _init_legacy(tmp_path, presets=["design-debate"])
    with pytest.raises(SchemaError, match="already selected"):
        scaffold_mod.add_preset(str(tmp_path), "design-debate")


def test_add_preset_preserves_hand_written_comments(tmp_path):
    _init_legacy(tmp_path)
    config_path = tmp_path / "refdes-project.yaml"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("site:", "# A hand-written comment nobody wants lost.\nsite:")
    config_path.write_text(text, encoding="utf-8")

    scaffold_mod.add_preset(str(tmp_path), "design-debate")
    after = config_path.read_text(encoding="utf-8")
    assert "# A hand-written comment nobody wants lost." in after


def test_remove_preset_removes_from_the_list(tmp_path):
    _init_legacy(tmp_path, presets=["design-debate"])
    scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    text = (tmp_path / "refdes-project.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text


def test_remove_preset_not_selected_is_an_error(tmp_path):
    _init_legacy(tmp_path)
    with pytest.raises(SchemaError, match="not currently selected"):
        scaffold_mod.remove_preset(str(tmp_path), "design-debate")


def test_remove_preset_reports_orphaned_items_before_writing(tmp_path):
    _init_legacy(tmp_path, presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    diagnostics = scaffold_mod.remove_preset(str(tmp_path), "design-debate")
    assert any(
        "unknown type 'debate'" in d.message and "design-debate" in d.message
        for d in diagnostics
    )
    # The report ran, but the config change still applied -- this command's
    # job is to surface the consequence, not block an author who already
    # decided to accept it.
    text = (tmp_path / "refdes-project.yaml").read_text(encoding="utf-8")
    assert "presets: []" in text
    # No leftover scratch file.
    assert not (tmp_path / "refdes-project.yaml.scratch").exists()


def test_cli_standard_add_and_remove_preset(tmp_path, capsys):
    _init_legacy(tmp_path)
    config = str(tmp_path / "refdes-project.yaml")
    status = cli_mod.main(["-c", config, "standard", "add-preset", "design-debate"])
    assert status == 0
    assert "design-debate" in (tmp_path / "refdes-project.yaml").read_text(encoding="utf-8")

    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 0
    assert "presets: []" in (tmp_path / "refdes-project.yaml").read_text(encoding="utf-8")


def test_cli_standard_remove_preset_exit_code_reflects_errors(tmp_path):
    _init_legacy(tmp_path, presets=["design-debate"])
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    config = str(tmp_path / "refdes-project.yaml")
    status = cli_mod.main(["-c", config, "standard", "remove-preset", "design-debate"])
    assert status == 1


# ---------------------------------------------- preset-provided diagnostics


def test_unknown_type_matching_a_preset_names_it(tmp_path):
    _init_legacy(tmp_path)  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "db-001.md").write_text(
        "---\nid: DB-001\ntype: debate\ntitle: An open question.\nstatus: open\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    assert any(
        "unknown type 'debate'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )


def test_unknown_type_with_no_preset_match_is_the_ordinary_message(tmp_path):
    _init_legacy(tmp_path)
    items = tmp_path / "items"
    items.mkdir()
    (items / "x.md").write_text(
        "---\nid: X-001\ntype: totallymadeup\ntitle: t.\n---\n", encoding="utf-8"
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    msg = next(d.message for d in project.errors if "unknown type" in d.message)
    assert "provided by" not in msg


def test_unknown_link_matching_a_preset_names_it(tmp_path):
    _init_legacy(tmp_path)  # no presets selected
    items = tmp_path / "items"
    items.mkdir()
    (items / "dec-001.md").write_text(
        "---\nid: DEC-001\ntype: decision\ntitle: t.\nstatus: accepted\n"
        "resolved_by: []\n---\n",
        encoding="utf-8",
    )
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    assert any(
        "unknown field 'resolved_by'" in d.message
        and "provided by the 'design-debate' preset" in d.message
        for d in project.errors
    )
