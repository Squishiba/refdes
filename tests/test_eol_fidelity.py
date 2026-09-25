"""Line endings survive every write-back, on every platform.

The bug this file exists for: a command that loads a project and writes a
source file back used to pick ONE line ending for the whole file -- typically
`"\\r\\n" if "\\r\\n" in text else "\\n"` -- and re-join every line with it. On
an all-LF file that was invisible; on an all-CRLF file PR #37's `newline=""`
reads had already made it invisible too. What it broke was the *third* case: a
file that already mixed. One CRLF line anywhere in it re-typed every untouched
line, so a one-line edit produced a whole-file diff that was nothing but line
endings. The same shape, in text mode rather than as a join, hit `former-ids
confirm` (a CRLF file came out LF on *every* platform) and `standard upgrade` /
`add-preset` / `remove-preset` (a CRLF config came out LF on Linux, an LF one
came out CRLF on Windows).

Every assertion here is written against bytes, never against `os.linesep` and
never against a platform's newline translation, so the same test means the same
thing on the Linux and Windows CI legs. The CRLF fixtures are written as
`b"..."` bytes on purpose: `write_text` on Windows would hand them straight to
the newline translation this file is testing against.
"""

from __future__ import annotations

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes import scaffold, textio

# A schema with the two link types the expansion paths need, so one fixture
# can exercise id allocation, key minting, and link expansion together.
EOL_SCHEMA = """\
site: {title: EOL, out: _site}
id: {width: 3, ledger: .refdes/ids.yaml}
link_types:
  satisfies: {inverse: satisfied_by, label: Satisfies}
types:
  requirement:
    prefix: REQ
    label: Requirement
    fields:
      text: {type: text, required: true}
    links: {}
  decision:
    prefix: DEC
    label: Decision
    fields:
      text: {type: text, required: true}
    links:
      satisfies: [requirement]
"""

# One item file per write-back path, each authored with LF. `_variant` below
# converts them to CRLF or leaves them alone; the mixed case is spelled out
# where it matters, because "half this file is CRLF" is the case the old
# whole-file test could not see.
LF_LIST = (
    b"items:\n"
    b"  - type: requirement\n"
    b"    text: Needs an id and a key.\n"
    b"    body: |\n"
    b"      One.\n"
    b"      Two.\n"
)
LF_MARKDOWN = (
    b"---\n"
    b"type: requirement\n"
    b"text: A hint to expand.\n"
    b"id: '042'\n"
    b"---\n"
    b"Body line one.\n"
    b"Body line two.\n"
)
LF_LINKS = (
    b"items:\n"
    b"  - id: REQ-001\n"
    b"    type: requirement\n"
    b"    text: The target.\n"
    b"  - id: DEC-001\n"
    b"    type: decision\n"
    b"    text: The source.\n"
    b"    satisfies: [REQ-001]\n"
)
# Front matter LF, body CRLF: a file that was already mixed before any tool
# touched it, which is the case this whole file is about.
LF_MIXED = (
    b"---\n"
    b"type: requirement\n"
    b"text: Already mixed.\n"
    b"---\n"
    b"Prose that must not move.\n"
    b"More prose.\n"
)
# No final line break at all: a write-back must not add one.
LF_NO_FINAL_BREAK = (
    b"---\n"
    b"type: requirement\n"
    b"text: No trailing newline.\n"
    b"---\n"
    b"Last line has no break after it."
)

SOURCES = {
    "fresh.yaml": LF_LIST,
    "hint.md": LF_MARKDOWN,
    "links.yaml": LF_LINKS,
    "mixed.md": LF_MIXED,
    "no-final-break.md": LF_NO_FINAL_BREAK,
}


# --------------------------------------------------------------------- helpers


def to_crlf(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def body_crlf(raw: bytes) -> bytes:
    """Front matter LF, everything after the closing fence CRLF."""
    head, sep, body = raw.partition(b"\n---\n")
    if not sep:
        return raw
    return head + sep + body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def eol_profile(raw: bytes) -> tuple[int, int]:
    """(CRLF lines, bare-LF lines), counted from the bytes.

    `os.linesep` is deliberately absent: the point of these tests is what is
    *on disk*, and on Windows the answer differs from what a text-mode write
    would have produced.
    """
    crlf = raw.count(b"\r\n")
    return crlf, raw.count(b"\n") - crlf


def assert_uniform(raw: bytes, *, eol: bytes) -> None:
    """Every line in `raw` ends with `eol`, and no other break is present."""
    crlf, lf = eol_profile(raw)
    if eol == b"\r\n":
        assert lf == 0, f"a bare LF crept into a CRLF file: {raw!r}"
        assert crlf > 0
    else:
        assert crlf == 0, f"a CRLF crept into an LF file: {raw!r}"
        assert lf > 0


def split_keeping_breaks(raw: bytes) -> list[bytes]:
    """`raw` as a list of (line content, terminator) pairs, from the bytes.

    `bytes.splitlines(keepends=True)` splits on the same set `str.splitlines`
    does, so this pairs up with `textio`'s own splitting -- which is what makes
    "line 3 of the file" mean the same thing in the test and in the code.
    """
    return raw.splitlines(keepends=True)


def assert_terminators_preserved(before: bytes, after: bytes) -> None:
    """Every line of `before` that is still present in `after` kept its ending.

    Matched by content, which is exactly the fidelity claim: an edit may
    change the text of the lines it means to change, but a line that survived
    the edit unchanged must also have kept the exact bytes that terminated it
    -- CRLF included. This is the assertion the old whole-file
    `newline.join(lines)` could not pass on a mixed file.
    """
    original = {ln.rstrip(b"\r\n"): ln[len(ln.rstrip(b"\r\n")) :] for ln in split_keeping_breaks(before)}
    for line in split_keeping_breaks(after):
        content = line.rstrip(b"\r\n")
        if content not in original:
            continue  # a line this edit added; its ending is asserted elsewhere
        assert line[len(content) :] == original[content], (
            f"line {content!r} survived the edit but its line ending changed: "
            f"{original[content]!r} -> {line[len(content):]!r}"
        )


def assert_no_body_line_removed(before: bytes, after: bytes) -> None:
    """No *prose* line of `before` is missing from `after`.

    Not every line, and deliberately so: a load-time write legitimately
    rewrites three kinds of line's text. A list entry's `- type: requirement`
    becomes `- id: REQ-001` plus an indented `type: requirement`; a
    bare-numeric `id: '042'` hint is replaced outright by the real id; and a
    bare `satisfies: [REQ-001]` becomes the composite `REQ-001@<key>`. Those are
    the edits. What must never change is a line that *kept* its text, and that
    is `assert_terminators_preserved`'s job -- this is the coarser companion:
    the file must not have lost prose.
    """
    after_contents = {ln.rstrip(b"\r\n") for ln in split_keeping_breaks(after)}
    rewritable = (b"type:", b"id:", b"satisfies:", b"checks:", b"follows:", b"key:")
    missing = [
        ln
        for ln in split_keeping_breaks(before)
        if ln.rstrip(b"\r\n") not in after_contents
        and not ln.rstrip(b"\r\n").lstrip().lstrip(b"- ").startswith(rewritable)
    ]
    assert not missing, f"lines disappeared that no edit should have removed: {missing!r}"


def make_project(tmp_path, convert) -> dict[str, bytes]:
    """A project whose item files have been run through `convert`."""
    write_project_config(tmp_path, EOL_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    written = {}
    for name, raw in SOURCES.items():
        data = convert(raw)
        (items / name).write_bytes(data)
        written[f"items/{name}"] = data
    return written


def read(root, rel: str) -> bytes:
    return (root / rel).read_bytes()


def read_item(root, name: str) -> bytes:
    return (root / "items" / name).read_bytes()


VARIANTS = {
    "lf": (lambda raw: raw, b"\n"),
    "crlf": (to_crlf, b"\r\n"),
}


@pytest.fixture(params=sorted(VARIANTS))
def variant(request):
    return VARIANTS[request.param]


# ------------------------------------------------------------------- textio


class TestSourceText:
    """The helper itself, independent of any command that uses it."""

    def test_an_lf_file_comes_back_lf(self):
        source = textio.SourceText("a\nb\nc\n")
        assert source.render(source.lines) == "a\nb\nc\n"

    def test_a_crlf_file_comes_back_crlf(self):
        text = "a\r\nb\r\nc\r\n"
        source = textio.SourceText(text)
        assert source.render(source.lines) == text

    def test_a_mixed_file_comes_back_byte_identical(self):
        text = "a\nb\r\nc\nd\r\n"
        source = textio.SourceText(text)
        assert source.render(source.lines) == text

    def test_an_inserted_line_takes_the_ending_of_the_line_it_displaces(self):
        """The rule that makes the mixed cases work: a new line lands in the
        slot the line below it used to terminate, so it wears that line's
        ending -- which is also the block it joined, since every insertion here
        puts a new `id:`/`key:` line at the top of an item and the item's own
        keys are below it."""
        assert textio.SourceText("a\r\nb\r\n").render(["a", "NEW", "b"]) == "a\r\nNEW\r\nb\r\n"
        assert textio.SourceText("a\nb\n").render(["a", "NEW", "b"]) == "a\nNEW\nb\n"
        # A file with a single line has no line below to ask; the line above
        # is the only neighbour, and the file's own style is the answer.
        assert textio.SourceText("a\n").render(["NEW", "a"]) == "NEW\na\n"

    def test_an_inserted_line_into_a_mixed_file_follows_its_neighbour(self):
        """The regression this module exists for: inserting between an LF line
        and a CRLF line must not re-type either of them."""
        # Into the CRLF block -> the new line is CRLF, the lone LF above it
        # stays LF, and the block it joined is untouched.
        assert textio.SourceText("a\nb\r\nc\r\n").render(["a", "NEW", "b", "c"]) == (
            "a\nNEW\r\nb\r\nc\r\n"
        )
        # Into the lone LF line -> it stays LF and the CRLF block is untouched.
        assert textio.SourceText("a\r\nb\n").render(["a", "NEW", "b"]) == (
            "a\r\nNEW\nb\n"
        )

    def test_an_edited_line_keeps_its_own_ending(self):
        """A replaced line is a replacement, not an insertion: it inherits the
        ending of the line it stands in for."""
        assert textio.SourceText("a\r\nb\r\n").render(["a", "B"]) == "a\r\nB\r\n"
        assert textio.SourceText("a\nb\n").render(["a", "B"]) == "a\nB\n"
        assert textio.SourceText("a\nb\r\n").render(["a", "B"]) == "a\nB\r\n"

    def test_a_file_with_no_final_break_does_not_acquire_one(self):
        """The trailing-newline fixup the old `join(lines) + newline` got
        wrong, and `revise` had to carry a special case for."""
        assert textio.SourceText("a\nb").render(["a", "B"]) == "a\nB"
        assert textio.SourceText("a\r\nb").render(["a", "B"]) == "a\r\nB"
        # Appending after an unterminated last line must supply the break the
        # old last line was missing -- two lines cannot share one terminator.
        assert textio.SourceText("a\nb").render(["a", "b", "c"]) == "a\nb\nc"

    def test_a_deletion_does_not_disturb_the_lines_around_it(self):
        assert textio.SourceText("a\nb\nc\n").render(["a", "c"]) == "a\nc\n"
        assert textio.SourceText("a\r\nb\r\nc\r\n").render(["a", "c"]) == "a\r\nc\r\n"

    def test_an_empty_file_renders_empty(self):
        assert textio.SourceText("").render([]) == ""
        assert textio.SourceText("").lines == []

    def test_dominant_is_the_majority_ending(self):
        assert textio.SourceText("a\nb\nc\n").dominant == "\n"
        assert textio.SourceText("a\r\nb\r\nc\r\n").dominant == "\r\n"
        # 2 CRLF against 3 LF: the majority wins, which is the whole point --
        # the old test was "does CRLF appear anywhere", which said CRLF here.
        assert textio.SourceText("a\r\nb\r\nc\nd\ne\n").dominant == "\n"
        assert textio.SourceText("a\nb\r\nc\r\nd\r\n").dominant == "\r\n"
        # A tie, and a file with no lines at all, both go to LF: `.gitattributes`
        # pins eol=lf, so LF is the answer when the file has not expressed one.
        assert textio.SourceText("a\nb\r\n").dominant == "\n"
        assert textio.SourceText("").dominant == "\n"

    def test_repeated_lines_do_not_shift_terminators_between_them(self):
        """difflib's `autojunk` heuristic calls a line that appears in more
        than 1% of a long sequence "popular" and stops matching it, which on an
        item file full of `- type: requirement` would align the wrong lines to
        the wrong terminators. This is the test that says we turned it off."""
        repeated = "".join("  - type: requirement\n" for _ in range(200))
        text = repeated + "    unique: one\n" + repeated
        source = textio.SourceText(text)
        lines = source.lines
        lines[200] = "    unique: two"
        assert source.render(lines) == text.replace("    unique: one\n", "    unique: two\n")

    def test_lines_hands_out_a_fresh_list(self):
        """Two callers editing the same file must not see each other's edits
        through a shared list."""
        source = textio.SourceText("a\nb\n")
        first = source.lines
        first[0] = "MUTATED"
        assert source.lines == ["a", "b"]
        assert source.render(source.lines) == "a\nb\n"

    def test_round_trips_every_str_splitlines_boundary(self):
        """`str.splitlines()` splits on more than \\n and \\r\\n. The terminator
        extractor has to agree with it about where the lines are, or
        `render()` attaches terminators to the wrong lines."""
        for boundary in "\n\r\v\f\x1c\x1d\x1e\x85  ":
            text = f"a{boundary}b{boundary}c"
            source = textio.SourceText(text)
            assert source.render(source.lines) == text, boundary


class TestReadWrite:
    def test_read_text_keeps_terminators_and_write_text_keeps_them(self, tmp_path):
        path = str(tmp_path / "f.md")
        for text in ("a\nb\n", "a\r\nb\r\n", "a\nb\r\nc\n"):
            textio.write_text(path, text)
            assert textio.read_text(path) == text
            assert (tmp_path / "f.md").read_bytes() == text.encode("utf-8")

    def test_write_text_does_not_translate_on_windows(self, tmp_path):
        """`newline=""` is the whole point of `write_text`. If it ever loses
        the argument, this fails on Windows and passes on Linux -- which is why
        it is written as an exact byte comparison rather than a round trip
        through `read_text`."""
        path = str(tmp_path / "f.md")
        textio.write_text(path, "a\nb\n")
        assert (tmp_path / "f.md").read_bytes() == b"a\nb\n"


class TestAppendEnding:
    """The appending twin of `render`, for the two callers that add a block to
    the end of a file instead of editing a line list."""

    def test_an_lf_file_appends_lf(self):
        assert textio.append_ending("a\nb\n") == "\n"

    def test_a_crlf_file_appends_crlf(self):
        assert textio.append_ending("a\r\nb\r\n") == "\r\n"

    def test_a_mixed_file_appends_the_style_of_its_last_line(self):
        """The editor regression: a file whose tail is LF but which mentions
        CRLF higher up used to hand the new item CRLF endings."""
        assert textio.append_ending("a\r\nb\n") == "\n"
        assert textio.append_ending("a\nb\r\n") == "\r\n"

    def test_a_file_with_no_final_break_still_answers_with_a_real_ending(self):
        """Not `""`. This is not deciding where the file's last line ends, it
        is deciding what to break the appended block's lines with, and both
        callers supply the break *in front of* the block themselves. An empty
        answer would run the block into the line above it."""
        assert textio.append_ending("a\nb") == "\n"
        assert textio.append_ending("a\r\nb") == "\r\n"

    def test_an_empty_file_has_no_neighbour_to_ask(self):
        assert textio.append_ending("") == "\n"


# ------------------------------------------------------- the write-back paths


class TestIdAllocation:
    def test_the_id_lines_arrive_in_the_files_own_ending(self, tmp_path, variant):
        convert, eol = variant
        make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        for name in SOURCES:
            assert_uniform(read_item(tmp_path, name), eol=eol)

    def test_a_crlf_file_is_not_converted_to_lf(self, tmp_path):
        make_project(tmp_path, to_crlf)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        assert b"\n" not in read_item(tmp_path, "hint.md").replace(b"\r\n", b"")

    def test_an_lf_file_is_not_converted_to_crlf(self, tmp_path):
        """The reported symptom, stated as the inverse: on Windows a text-mode
        write handed the whole file to the newline translation, so an LF file
        came back CRLF after a one-line edit."""
        make_project(tmp_path, lambda raw: raw)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        assert b"\r\n" not in read_item(tmp_path, "fresh.yaml")

    def test_a_mixed_file_is_not_normalized(self, tmp_path):
        """The regression: one CRLF line in the body used to re-type the whole
        file. Front matter and body must each keep what they had."""
        make_project(tmp_path, lambda raw: raw)
        (tmp_path / "items" / "mixed.md").write_bytes(body_crlf(LF_MIXED))
        before = read_item(tmp_path, "mixed.md")
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        after = read_item(tmp_path, "mixed.md")

        assert_terminators_preserved(before, after)
        assert_no_body_line_removed(before, after)
        lines = after.split(b"\n")
        # The body is still CRLF, every one of those lines.
        assert lines.count(b"Prose that must not move.\r") == 1
        assert lines.count(b"More prose.\r") == 1
        # ...and the id/key lines went into the LF front matter as LF lines.
        added = [ln for ln in lines if ln.startswith((b"id: REQ-", b"key: "))]
        assert added, after
        assert all(not ln.endswith(b"\r") for ln in added), added

    def test_a_file_with_no_final_break_still_has_none(self, tmp_path, variant):
        convert, _eol = variant
        make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        raw = read_item(tmp_path, "no-final-break.md")
        assert raw.endswith(b"Last line has no break after it."), raw

    def test_only_the_lines_the_edit_touched_change(self, tmp_path, variant):
        convert, _eol = variant
        before = make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        for rel, raw in before.items():
            after = read(tmp_path, rel)
            # The real claim: a line that survived the edit with its text
            # intact also kept the exact bytes that terminated it.
            assert_terminators_preserved(raw, after)
            assert_no_body_line_removed(raw, after)
            # The only content that appears is an id:/key:/link line, or the
            # re-indented `type:` half of a list entry that gained an id.
            original = {ln.rstrip(b"\r\n") for ln in split_keeping_breaks(raw)}
            added = [
                ln
                for ln in split_keeping_breaks(after)
                if ln.rstrip(b"\r\n") not in original
            ]
            assert all(
                ln.rstrip(b"\r\n").lstrip().lstrip(b"- ").startswith(
                    (b"id:", b"key:", b"type:", b"satisfies:")
                )
                for ln in added
            ), (rel, added)


class TestKeyMinting:
    def test_a_minted_key_line_takes_its_neighbours_ending(self, tmp_path, variant):
        convert, eol = variant
        make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        for name in SOURCES:
            raw = read_item(tmp_path, name)
            assert b"key: " in raw, name
            assert_uniform(raw, eol=eol)

    def test_minting_into_a_mixed_file_keeps_both_halves(self, tmp_path):
        make_project(tmp_path, lambda raw: raw)
        (tmp_path / "items" / "mixed.md").write_bytes(body_crlf(LF_MIXED))
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        lines = read_item(tmp_path, "mixed.md").split(b"\n")
        # The key was minted into the LF front matter, so it is an LF line...
        assert any(
            ln.startswith(b"key: ") and not ln.endswith(b"\r") for ln in lines
        ), lines
        # ...and the CRLF body is untouched.
        assert lines.count(b"Prose that must not move.\r") == 1
        assert lines.count(b"More prose.\r") == 1

    def test_minting_under_no_write_touches_nothing(self, tmp_path, variant):
        convert, _eol = variant
        before = make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        cli_mod.main(["-c", cfg, "--no-write", "check"])
        for rel, raw in before.items():
            assert read(tmp_path, rel) == raw


class TestLinkExpansion:
    def test_a_bare_target_becomes_a_composite_in_the_files_own_ending(
        self, tmp_path, variant
    ):
        convert, eol = variant
        make_project(tmp_path, convert)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        raw = read_item(tmp_path, "links.yaml")
        assert_uniform(raw, eol=eol)
        expanded = [ln for ln in raw.split(b"\n") if ln.startswith(b"    satisfies:")]
        assert expanded, raw
        assert all(b"@" in ln for ln in expanded), expanded

    def test_expansion_into_a_mixed_file_keeps_both_halves(self, tmp_path):
        """A markdown file whose front matter is LF and whose body is CRLF,
        with a bare link in the front matter: the expanded target must not
        drag CRLF into the block it sits in."""
        write_project_config(tmp_path, EOL_SCHEMA)
        items = tmp_path / "items"
        items.mkdir()
        (items / "target.yaml").write_bytes(
            b"items:\n  - id: REQ-001\n    type: requirement\n    text: T\n"
        )
        (items / "src.md").write_bytes(
            b"---\n"
            b"id: DEC-001\n"
            b"type: decision\n"
            b"text: S\n"
            b"satisfies: [REQ-001]\n"
            b"---\n"
            b"Body line.\r\n"
            b"Second line.\r\n"
        )
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        lines = (items / "src.md").read_bytes().split(b"\n")
        link = next(ln for ln in lines if ln.startswith(b"satisfies:"))
        assert b"@" in link, link
        assert not link.endswith(b"\r"), "the front matter is LF; expansion made it CRLF"
        assert lines.count(b"Body line.\r") == 1
        assert lines.count(b"Second line.\r") == 1


class TestFormerIds:
    def test_confirm_preserves_a_crlf_file(self, tmp_path):
        """This path read in *text mode*, so by the time it chose a style every
        CRLF was already an LF -- a CRLF file came out LF on every platform,
        not just Windows."""
        project, path = _former_ids_project(tmp_path, crlf=True)
        _confirm_one(project)
        raw = path.read_bytes()
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b""), "a lone LF crept in"

    def test_confirm_preserves_an_lf_file(self, tmp_path):
        project, path = _former_ids_project(tmp_path, crlf=False)
        _confirm_one(project)
        assert b"\r\n" not in path.read_bytes()

    def test_confirm_preserves_a_mixed_file(self, tmp_path):
        project, path = _former_ids_project(tmp_path, crlf=False)
        path.write_bytes(body_crlf(path.read_bytes()))
        _confirm_one(project)
        lines = path.read_bytes().split(b"\n")
        assert lines.count(b"Body line.\r") == 1
        assert lines.count(b"Second line.\r") == 1
        added = next(ln for ln in lines if ln.startswith(b"former_ids:"))
        assert not added.endswith(b"\r"), "it joined the LF front matter"


def _former_ids_project(tmp_path, *, crlf: bool):
    """A project whose stamped baseline names an item that is no longer there,
    with a new item of the same type and title to stand in for it -- which is
    what `former-ids propose` matches a candidate on."""
    from refdes import build as build_mod
    from refdes import lifecycle, parse as parse_mod
    from refdes.schema import load_project

    write_project_config(tmp_path, EOL_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    path = items / "r.md"
    before = (
        b"---\n"
        b"id: REQ-001\n"
        b"type: requirement\n"
        b"text: Renumbered.\n"
        b"---\n"
        b"Body line.\n"
        b"Second line.\n"
    )
    after = before.replace(b"id: REQ-001", b"id: REQ-042")

    def _write(raw: bytes) -> None:
        path.write_bytes(to_crlf(raw) if crlf else raw)

    def _build():
        project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
        parse_mod.load_items(project, require_ids=False)
        build_mod.build(project, seal_write=False, reseal=False)
        return project

    _write(before)
    lifecycle.stamp(_build(), kind="revision", name="rev-a")
    _write(after)
    return _build(), path


def _confirm_one(project) -> None:
    from refdes import former_ids as former_ids_mod

    candidates = former_ids_mod.propose(project)
    assert candidates, "propose found no candidate; the fixture is wrong"
    former_ids_mod.confirm(project, candidates, [c.old_id for c in candidates])


class TestConfigWrites:
    """`refdes-project.yaml` is hand-authored and hand-commented, so every
    command that touches it edits a span and leaves the rest alone -- which
    only means anything if the rest keeps its bytes."""

    # `add-preset`/`remove-preset` need a `standard:` block, and the bump needs
    # a `version:` to move. A config of its own rather than EOL_SCHEMA, whose
    # types would then come from the bundled standard instead of the fixture.
    CONFIG = (
        "site: {title: EOL, out: _site}\n"
        "standard: {base: hardware, version: 3, presets: []}\n"
        "id: {width: 3, ledger: .refdes/ids.yaml}\n"
    )

    def _config(self, root, *, crlf: bool):
        path = root / "refdes-project.yaml"
        raw = self.CONFIG.encode("utf-8")
        path.write_bytes(to_crlf(raw) if crlf else raw)
        return path

    def test_add_preset_preserves_a_crlf_config(self, tmp_path):
        path = self._config(tmp_path, crlf=True)
        scaffold.add_preset(str(tmp_path), "design-debate")
        raw = path.read_bytes()
        assert b"design-debate" in raw
        assert b"\n" not in raw.replace(b"\r\n", b""), raw

    def test_add_preset_preserves_an_lf_config(self, tmp_path):
        path = self._config(tmp_path, crlf=False)
        scaffold.add_preset(str(tmp_path), "design-debate")
        assert b"\r\n" not in path.read_bytes()

    def test_remove_preset_preserves_the_config(self, tmp_path):
        for crlf in (True, False):
            root = tmp_path / f"crlf-{crlf}"
            root.mkdir()
            path = self._config(root, crlf=crlf)
            scaffold.add_preset(str(root), "design-debate")
            scaffold.remove_preset(str(root), "design-debate")
            raw = path.read_bytes()
            assert b"design-debate" not in raw
            if crlf:
                assert b"\n" not in raw.replace(b"\r\n", b""), raw
            else:
                assert b"\r\n" not in raw, raw

    def test_standard_upgrade_preserves_the_config(self, tmp_path):
        """`_bump_standard_version` read with `splitlines(keepends=True)` over a
        text-mode read and wrote with a bare `open(..., "w")`: bumping one
        number rewrote a CRLF config to all-LF on Linux and an LF config to
        all-CRLF on Windows."""
        from refdes import revise

        for crlf in (True, False):
            root = tmp_path / f"upgrade-{crlf}"
            root.mkdir()
            path = self._config(root, crlf=crlf)
            before = to_crlf(path.read_bytes()) if crlf else path.read_bytes()
            revise._bump_standard_version(str(path), 99)
            raw = path.read_bytes()
            assert b"version: 99" in raw, raw
            if crlf:
                assert b"\n" not in raw.replace(b"\r\n", b""), raw
            else:
                assert b"\r\n" not in raw, raw
            # And nothing but the number moved.
            assert raw == before.replace(b"version: 3", b"version: 99")


class TestEditorCreate:
    def test_appending_to_an_lf_file_does_not_add_crlf(self, tmp_path):
        """The editor's create-item path asked "does this file mention CRLF
        anywhere" and appended in that style. A single CRLF line high up in an
        otherwise-LF file put the new item in wearing CRLF."""
        root, path = _editor_project(tmp_path, crlf=False)
        _create_one(root)
        raw = path.read_bytes()
        assert b"\r\n" not in raw, raw
        assert b"id: DEC-001" in raw

    def test_appending_to_a_crlf_file_adds_crlf(self, tmp_path):
        root, path = _editor_project(tmp_path, crlf=True)
        _create_one(root)
        raw = path.read_bytes()
        assert b"\n" not in raw.replace(b"\r\n", b""), raw

    def test_appending_to_a_mixed_file_follows_its_last_line(self, tmp_path):
        root, path = _editor_project(tmp_path, crlf=True)
        # A file that is CRLF everywhere except its last line, which is LF:
        # the new block is appended after that last line, so it is LF too.
        raw = path.read_bytes()
        assert raw.endswith(b"\r\n")
        path.write_bytes(raw[:-2] + b"\n")
        _create_one(root)
        lines = path.read_bytes().split(b"\n")
        new_item = [ln for ln in lines if b"id: DEC-001" in ln]
        assert new_item and not new_item[0].endswith(b"\r"), lines
        # ...and the CRLF block above it did not move.
        assert lines.count(b"  - id: REQ-001\r") == 1
        # ...and the new block is internally consistent.
        assert lines[-2] and not lines[-2].endswith(b"\r"), lines


def _editor_project(tmp_path, *, crlf: bool):
    write_project_config(tmp_path, EOL_SCHEMA)
    items = tmp_path / "items"
    items.mkdir()
    path = items / "r.yaml"
    raw = b"items:\n  - id: REQ-001\n    type: requirement\n    text: T\n"
    path.write_bytes(to_crlf(raw) if crlf else raw)
    return tmp_path, path


def _create_one(root) -> None:
    """Drive `serve.edit.create_item` for one decision item, appending to the
    existing list file -- the shape that exercises the append path."""
    from refdes.serve.edit import CreateRequest, create_item

    request = CreateRequest(
        who="test",
        type="decision",
        fields={"text": "Created by the editor."},
        destination="items/r.yaml",
    )
    result = create_item(str(root), request)
    assert result.ok, result.message


class TestGeneratedState:
    """Machine-owned files the tool regenerates whole. Their bytes must not
    depend on which platform last wrote them -- they are committed."""

    def test_the_id_ledger_is_the_same_on_every_platform(self, tmp_path):
        make_project(tmp_path, lambda raw: raw)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        ledger = read(tmp_path, ".refdes/ids.yaml")
        assert b"\r\n" not in ledger, ledger

    def test_the_schema_json_is_the_same_on_every_platform(self, tmp_path):
        make_project(tmp_path, lambda raw: raw)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        assert (tmp_path / ".refdes" / "schema.json").is_file()
        schema = read(tmp_path, ".refdes/schema.json")
        assert b"\r\n" not in schema

    def test_history_objects_are_the_same_on_every_platform(self, tmp_path):
        """Content-addressed and immutable: the same item must produce the same
        bytes whoever captures it, or the address stops addressing."""
        from refdes import history as history_mod
        from refdes import parse as parse_mod
        from refdes.schema import load_project

        make_project(tmp_path, lambda raw: raw)
        project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
        parse_mod.load_items(project, require_ids=True)
        item = next(i for i in project.local_items if i.id)
        root = str(tmp_path / ".refdes" / "history")
        history_mod.save_object(root, item)
        written = list((tmp_path / ".refdes" / "history").rglob("*.yaml"))
        assert written, "save_object wrote nothing"
        for path in written:
            assert b"\r\n" not in path.read_bytes(), path


class TestBuildOutputIsUnchanged:
    """The one deliberate exception. Site HTML and the manifest are build
    output, not source: they are written in text mode on purpose so a Windows
    build produces Windows line endings, and nothing in this change may start
    forcing LF on them."""

    def test_site_output_is_still_written_the_way_it_always_was(self, tmp_path):
        """`render` is untouched. This test exists to say so: the site still
        builds, and the line endings on disk are the platform's own rather than
        a hardcoded LF. The assertions are deliberately about *whole* breaks --
        a `\\r\\r\\n` here would mean somebody started composing CRLF by hand on
        top of a translating writer."""
        make_project(tmp_path, lambda raw: raw)
        cfg = str(tmp_path / "refdes-project.yaml")
        assert cli_mod.main(["-c", cfg, "id"]) == 0
        cli_mod.main(["-c", cfg, "build"])
        index = tmp_path / "_site" / "index.html"
        assert index.is_file()
        raw = index.read_bytes()
        assert b"<html" in raw.lower()
        # A doubled CR is the fingerprint of composing CRLF by hand on top of
        # a writer that already translates. `render` is deliberately untouched,
        # so this must not appear.
        assert b"\r\r" not in raw
        # Site output is the documented exception: it is *not* normalized to LF,
        # because a Windows build is expected to produce Windows line endings.
        # So on Windows this file is CRLF and on Linux it is LF. Either is
        # correct; what must not happen is a mixture within one file.
        _crlf, lf = eol_profile(raw)
        assert not (lf and _crlf), "the site build mixed line endings in one file"
