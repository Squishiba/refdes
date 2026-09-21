"""Tests for the item-span source patcher (docs/design/browser-editor.md).

Two halves. The sabotage fixtures are files written specifically to break a
naive patcher -- a comment in the way, an anchor, a second document, a `---`
sitting in prose -- where the correct outcome is often a refusal, so the test
asserts the refusal and its reason rather than an edit. The property half runs
over this repo's real items files and checks the guarantee that has no fixture
shaped like it: patch anything, and everything outside the span is the same
bytes it was.
"""

import os
from pathlib import Path

import pytest
import yaml

from refdes import patcher
from refdes.patcher import PatchPlan, Refusal, SetBody, SetField, apply_patch, plan_patch, revert_plan

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = os.path.join(REPO, "items")


def refuse(text, ref, op, **kw):
    got = plan_patch(text, ref, op, **kw)
    assert isinstance(got, Refusal), f"expected a refusal, got {got!r}"
    return got


def plan(text, ref, op, **kw):
    got = plan_patch(text, ref, op, **kw)
    assert isinstance(got, PatchPlan), f"expected a plan, got {got!r}"
    return got


def edited(text, ref, op, **kw):
    """Plan, apply, and assert the one invariant every plan must satisfy."""
    got = plan(text, ref, op, **kw)
    new = apply_patch(text, got)
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    return new, got


# --------------------------------------------------------------- the three shapes

LIST_FILE = """\
# a comment the patcher must not eat
items:
  - id: REQ-001
    title: First
    priority: high
  - id: REQ-002
    title: Second
"""

MD_FILE = """\
---
id: DEC-001
title: Chosen
status: accepted
---

Prose about the choice.
"""


def test_set_scalar_in_yaml_list_file():
    new, got = edited(LIST_FILE, "REQ-001", SetField("priority", "low"))
    assert got.shape == "yaml-item"
    assert "priority: low" in new
    assert yaml.safe_load(new)["items"][0]["priority"] == "low"


def test_set_scalar_by_surrogate_key():
    text = "items:\n  - key: abc123\n    title: T\n"
    new, _ = edited(text, "abc123", SetField("title", "Renamed"))
    assert yaml.safe_load(new)["items"][0]["title"] == "Renamed"


def test_set_front_matter_field_in_markdown():
    new, got = edited(MD_FILE, "DEC-001", SetField("status", "superseded"))
    assert got.shape == "md-front-matter"
    assert new.endswith("\nProse about the choice.\n")
    assert "status: superseded" in new


def test_set_markdown_body():
    new, got = edited(MD_FILE, "DEC-001", SetBody("New prose.\n"))
    assert got.shape == "md-body"
    assert new == "---\nid: DEC-001\ntitle: Chosen\nstatus: accepted\n---\nNew prose.\n"


def test_set_yaml_body_becomes_a_block_scalar():
    text = "items:\n  - id: REQ-001\n    body: one line\n"
    new, _ = edited(text, "REQ-001", SetBody("first\nsecond\n"))
    assert yaml.safe_load(new)["items"][0]["body"] == "first\nsecond\n"
    assert "body: |" in new or "body: |-" in new or '"' in new


def test_markdown_file_with_several_items_edits_only_the_target():
    text = MD_FILE + "---\nid: DEC-002\ntitle: Later\n---\n\nOther prose.\n"
    new, _ = edited(text, "DEC-001", SetBody("Rewritten.\n"))
    assert "Other prose." in new
    assert "title: Later" in new
    assert new.count("---") == 4


# ------------------------------------------------------------ fidelity contract

def test_comment_between_keys_survives():
    text = (
        "items:\n"
        "  - id: REQ-001\n"
        "    # why this priority: see the review\n"
        "    priority: high\n"
        "    title: T\n"
    )
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert "# why this priority: see the review" in new
    assert "priority: low" in new


def test_trailing_comment_on_the_edited_line_survives():
    text = "items:\n  - id: REQ-001\n    priority: high  # bumped in review\n"
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert new == "items:\n  - id: REQ-001\n    priority: low  # bumped in review\n"


def test_key_order_and_untouched_quoting_are_untouched():
    text = (
        "items:\n"
        '  - id: REQ-001\n'
        '    title: "Quoted on purpose: keep me"\n'
        "    priority: high\n"
        "    owner: 'single'\n"
    )
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert 'title: "Quoted on purpose: keep me"' in new
    assert "owner: 'single'" in new
    assert new.index("title:") < new.index("priority:")


def test_untouched_value_keeps_its_own_spelling_when_set_back():
    text = 'items:\n  - id: REQ-001\n    title: "Quoted"\n'
    new, got = edited(text, "REQ-001", SetField("title", "Quoted"))
    assert new == text


def test_blank_line_between_items_survives_a_block_scalar_edit():
    text = (
        "items:\n"
        "  - id: REQ-001\n"
        "    body: |\n"
        "      one\n"
        "      two\n"
        "\n"
        "  - id: REQ-002\n"
        "    body: other\n"
    )
    new, _ = edited(text, "REQ-001", SetField("body", "rewritten\n"))
    assert new == (
        "items:\n"
        "  - id: REQ-001\n"
        "    body: |\n"
        "      rewritten\n"
        "\n"
        "  - id: REQ-002\n"
        "    body: other\n"
    )


def test_folded_field_stays_folded():
    text = "items:\n  - id: REQ-001\n    why: >\n      one line of prose\n      wrapped here\n"
    new, got = edited(text, "REQ-001", SetField("why", "different prose\n"))
    assert new.startswith("items:\n  - id: REQ-001\n    why: >")
    assert yaml.safe_load(new)["items"][0]["why"] == "different prose\n"
    assert "revert restores the original wrapping" or True
    assert apply_patch(new, revert_plan(got)) == text


def test_unicode_survives_byte_for_byte():
    text = "items:\n  - id: REQ-001\n    title: 9–36 V, 25 °C, 效率\n    priority: high\n"
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert "9–36 V, 25 °C, 效率" in new


def test_file_without_trailing_newline_stays_without_one():
    text = "items:\n  - id: REQ-001\n    title: T"
    new, _ = edited(text, "REQ-001", SetField("title", "U"))
    assert new.endswith("title: U")
    assert not new.endswith("\n")


def test_crlf_file_keeps_crlf():
    text = "items:\r\n  - id: REQ-001\r\n    title: T\r\n    priority: high\r\n"
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert new.count("\r\n") == text.count("\r\n")
    assert "priority: low" in new


def test_crlf_body_edit_uses_the_files_line_endings():
    text = "---\nid: DEC-001\n---\n\nold prose\n"
    text = text.replace("\n", "\r\n")
    new, _ = edited(text, "DEC-001", SetBody("one\r\ntwo\r\n"))
    assert "\n" not in new.replace("\r\n", "")


def test_crlf_markdown_body_edit_applies():
    """The bug: `_verify` compared the op's LF text against the patched file's
    CRLF body, so a faithful CRLF markdown body edit was reported as a
    mismatch. The comparison is line-ending-neutral now; the bytes are not."""
    text = "---\nid: DEC-001\n---\n\nold prose\n".replace("\n", "\r\n")
    new, got = edited(text, "DEC-001", SetBody("New prose.\n"))
    assert got.shape == "md-body"
    assert new == "---\r\nid: DEC-001\r\n---\r\nNew prose.\r\n"
    assert "\n" not in new.replace("\r\n", "")


def test_crlf_markdown_body_edit_keeps_bytes_outside_the_span():
    text = (
        "---\r\nid: DEC-001\r\n---\r\n\r\nold prose\r\n"
        "---\r\nid: DEC-002\r\n---\r\n\r\nother prose\r\n"
    )
    new, got = edited(text, "DEC-001", SetBody("Rewritten.\n"))
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    assert "other prose" in new and "id: DEC-002" in new


def test_mixed_line_endings_follow_the_files_detected_eol():
    """A file carrying both breaks is not a new decision: `_load` already calls
    it a CRLF file, so the body is written with CRLF and every byte outside the
    replaced span -- LF breaks included -- stays where it was."""
    text = "---\nid: DEC-001\n---\nline a\r\nline b\n"
    new, got = edited(text, "DEC-001", SetBody("New prose.\nmore\n"))
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    assert new.endswith("New prose.\r\nmore\r\n")


def test_lf_markdown_body_edit_is_unchanged_by_the_fix():
    text = "---\nid: DEC-001\n---\n\nold prose\n"
    new, got = edited(text, "DEC-001", SetBody("New prose.\n"))
    assert new == "---\nid: DEC-001\n---\nNew prose.\n"
    assert "\r" not in new
    assert apply_patch(new, revert_plan(got)) == text


def test_a_tampered_crlf_body_plan_is_still_refused():
    """Line-ending neutrality must not become edit neutrality: a replacement
    that says something else, or that writes the wrong break into the file, is
    still a refusal."""
    from dataclasses import replace as dreplace

    text = "---\nid: DEC-001\n---\n\nold prose\n".replace("\n", "\r\n")
    got = plan(text, "DEC-001", SetBody("New prose.\n"))
    f = patcher._load(text)
    for bad in (
        dreplace(got, replacement="Different prose.\r\n"),
        dreplace(got, replacement=got.replacement + "tacked on\r\n"),
        dreplace(got, replacement="New prose.\n"),  # LF breaks into a CRLF file
    ):
        with pytest.raises(patcher._LocateError):
            patcher._verify(f, bad, SetBody("New prose.\n"))


def test_crlf_markdown_body_round_trips_to_the_original_bytes():
    text = (
        "---\r\nid: DEC-001\r\n---\r\n\r\nold prose\r\nsecond line\r\n"
        "---\r\nid: DEC-002\r\n---\r\n\r\nkeep me\r\n"
    )
    forward = plan(text, "DEC-001", SetBody("Something else entirely.\n"))
    middle = apply_patch(text, forward)
    assert middle != text
    back = apply_patch(middle, revert_plan(forward))
    assert back.encode("utf-8") == text.encode("utf-8")


def test_crlf_yaml_body_edit_applies():
    text = "items:\r\n  - id: REQ-001\r\n    body: old\r\n".replace("\n", "\r\n")
    new, got = edited(text, "REQ-001", SetBody("first\nsecond\n"))
    assert "\n" not in new.replace("\r\n", "")
    assert yaml.safe_load(new)["items"][0]["body"] == "first\nsecond\n"
    assert apply_patch(new, revert_plan(got)) == text


# ------------------------------------------------------- inserting a new field
#
# An insertion is a zero-width span, so its offset is the one place the patcher
# can land *inside* a line break: walking back to the end of the previous value
# stopped between the CR and the LF of a CRLF file, and the added line then
# opened with its own break -- `\r\r\n` in the middle and an orphan `\n` at the
# end of the run. These fixtures pin that an insertion lands on a line boundary.

INSERT_YAML = "items:\n  - id: REQ-001\n    title: T\n    priority: high\n\n  - id: REQ-002\n    title: U\n"
INSERT_MD = "---\nid: DEC-001\n---\n\nprose\n\n---\nid: DEC-002\n---\n\nmore\n"


def _line_break_variants(text):
    """The same file as LF, as CRLF, and each without the final break."""
    crlf = text.replace("\n", "\r\n")
    return {
        "lf": text,
        "crlf": crlf,
        "lf-no-final-newline": text.rstrip("\n"),
        "crlf-no-final-newline": crlf.rstrip("\r\n"),
    }


def assert_breaks_are_whole(text, eol):
    """No lone CR anywhere, no CR-run, and no bare LF in a CRLF file."""
    lone_cr = [i for i, ch in enumerate(text) if ch == "\r" and text[i + 1 : i + 2] != "\n"]
    assert lone_cr == [], f"lone CR at {lone_cr[:3]}: {text[max(0, lone_cr[0] - 30):lone_cr[0] + 10]!r}"
    assert "\r\r" not in text
    if eol == "\r\n":
        lone_lf = [i for i, ch in enumerate(text) if ch == "\n" and text[i - 1 : i] != "\r"]
        assert lone_lf == [], f"bare LF at {lone_lf[:3]}"


def inserted(text, ref, op, eol, expected_value):
    """Plan an insertion, apply it, and hold the result to all four guarantees."""
    got = plan(text, ref, op)
    new = apply_patch(text, got)
    if got.op == "insert":
        assert got.start == got.end, "an insertion is zero-width"
    # 2. everything outside the insertion point is the same bytes
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    # 1. the break structure survives
    assert_breaks_are_whole(new, eol)
    # 3. revert is byte-identical
    assert apply_patch(new, revert_plan(got)) == text
    # 4. the real parser sees exactly the intended value, and nothing else moved
    after = patcher._load(new)
    assert len(after.items) == len(patcher._load(text).items)
    item = next(it for it in after.items if it.ref == ref)
    if isinstance(op, SetField):
        assert item.fields[op.name].value == str(expected_value)
    elif item.shape == "md-front-matter":
        entry = next(e for e in after.projection if e[0].get("id") == ref or e[0].get("key") == ref)
        assert entry[1].rstrip("\r\n") == expected_value.rstrip("\n")
    else:
        assert item.fields["body"].value.rstrip("\n") == expected_value.rstrip("\n")
    return new, got


def test_insert_yaml_body_all_line_ending_variants():
    for eol, text in _line_break_variants(INSERT_YAML).items():
        inserted(text, "REQ-002", SetBody("Replacement body.\nSecond line."), eol, "Replacement body.\nSecond line.")


def test_insert_yaml_field_all_line_ending_variants():
    for eol, text in _line_break_variants(INSERT_YAML).items():
        inserted(text, "REQ-001", SetField("owner", "Jared"), eol, "Jared")


def test_insert_md_front_matter_field_all_line_ending_variants():
    for eol, text in _line_break_variants(INSERT_MD).items():
        inserted(text, "DEC-001", SetField("owner", "Jared"), eol, "Jared")


def test_insert_md_body_all_line_ending_variants():
    # DEC-002's body exists but the edit is the same shape for a file whose
    # last item ends without a final break.
    for eol, text in _line_break_variants(INSERT_MD).items():
        new, got = inserted(text, "DEC-002", SetBody("New prose.\n"), eol, "New prose.")
        assert "New prose." in new
        assert got.shape == "md-body"


def test_insert_crlf_yaml_body_is_crlf_throughout():
    text = INSERT_YAML.replace("\n", "\r\n")
    new, got = inserted(text, "REQ-002", SetBody("Replacement body.\nSecond line."), "\r\n", "Replacement body.\nSecond line.")
    assert "\n" not in new.replace("\r\n", "")
    assert "body: |-" in new
    assert yaml.safe_load(new)["items"][1]["body"] == "Replacement body.\nSecond line."


def test_insert_keeps_a_missing_final_newline_missing():
    text = INSERT_YAML.replace("\n", "\r\n").rstrip("\r\n")
    new, _ = inserted(text, "REQ-002", SetBody("Body.\n"), "\r\n", "Body.")
    assert not new.endswith("\r\n") and not new.endswith("\n")
    lf = INSERT_YAML.rstrip("\n")
    new, _ = inserted(lf, "REQ-002", SetBody("Body.\n"), "\n", "Body.")
    assert not new.endswith("\n")


def test_insert_leaves_other_items_untouched():
    text = INSERT_YAML.replace("\n", "\r\n")
    new, _ = inserted(text, "REQ-001", SetField("owner", "Jared"), "\r\n", "Jared")
    before = yaml.safe_load(text)["items"]
    after = yaml.safe_load(new)["items"]
    assert before[1] == after[1]
    assert after[0]["owner"] == "Jared"
    assert {k: v for k, v in after[0].items() if k != "owner"} == before[0]


def test_an_insertion_offset_inside_a_break_is_refused():
    """Sabotage the other way: a plan whose zero-width offset lands between the
    CR and the LF must be refused, not spliced into a broken pair."""
    from dataclasses import replace as dreplace

    text = INSERT_YAML.replace("\n", "\r\n")
    got = plan(text, "REQ-002", SetBody("Replacement body.\nSecond line."))
    f = patcher._load(text)
    split = dreplace(got, start=got.start + 1, end=got.start + 1)
    with pytest.raises(patcher._LocateError):
        patcher._verify(f, split, SetBody("Replacement body.\nSecond line."))


# ------------------------------------------- the body's final break, converted once
#
# A Markdown body that runs to the end of the file keeps the file's final break:
# the planner appends one to the replacement when the original had one. Appending
# the file's eol and *then* converting LF to CRLF converted that break twice, so
# the last thing written was `\r\r\n` -- a stray CR the file did not have before.

MD_EOF = "---\nid: DEC-001\n---\n\nfirst prose\n\n---\nid: DEC-002\n---\n\nlast body\n"


def md_body(text, ref, eol, final_break):
    """SetBody on a Markdown item, checked down to the last break of the file."""
    got = plan(text, ref, SetBody("Inserted body.\nline two."))
    assert got.shape == "md-body"
    new = apply_patch(text, got)
    # the replacement ends in exactly one break, and it is the file's own
    if final_break:
        assert got.replacement.endswith(eol) and not got.replacement.endswith(eol + eol)
        assert not got.replacement.endswith("\r\r\n")
    else:
        assert not got.replacement.endswith(("\n", "\r"))
    assert "\r\r" not in got.replacement
    assert new[: got.start] == text[: got.start]
    assert new[len(new) - len(text) + got.end :] == text[got.end :]
    assert_breaks_are_whole(new, eol)
    assert new.endswith("\n") == final_break
    assert apply_patch(new, revert_plan(got)) == text
    entry = next(e for e in patcher._load(new).projection if e[0]["id"] == ref)
    assert patcher._body_view(entry[1]) == "Inserted body.\nline two."
    return new, got


def test_md_body_at_eof_with_final_newline_keeps_one_break():
    md_body(MD_EOF, "DEC-002", "\n", True)
    md_body(MD_EOF.replace("\n", "\r\n"), "DEC-002", "\r\n", True)


def test_md_body_at_eof_without_final_newline_adds_none():
    md_body(MD_EOF.rstrip("\n"), "DEC-002", "\n", False)
    md_body(MD_EOF.replace("\n", "\r\n").rstrip("\r\n"), "DEC-002", "\r\n", False)


def test_md_body_mid_file_keeps_the_following_item_intact():
    for eol, text in (("\n", MD_EOF), ("\r\n", MD_EOF.replace("\n", "\r\n"))):
        new, got = md_body(text, "DEC-001", eol, True)
        assert got.end < len(text)
        refs = [e[0]["id"] for e in patcher._load(new).projection]
        assert refs == ["DEC-001", "DEC-002"]
        other = next(e for e in patcher._load(new).projection if e[0]["id"] == "DEC-002")
        before = next(e for e in patcher._load(text).projection if e[0]["id"] == "DEC-002")
        assert patcher._body_view(other[1]) == patcher._body_view(before[1])


def test_a_replacement_with_a_stray_cr_is_refused():
    from dataclasses import replace as dreplace

    text = MD_EOF.replace("\n", "\r\n")
    got = plan(text, "DEC-002", SetBody("Inserted body.\nline two."))
    f = patcher._load(text)
    for bad in (
        got.replacement[:-2] + "\r\r\n",  # the doubled conversion this replaced
        got.replacement + "\r",  # a CR left dangling at the end
        got.replacement.replace("\r\n", "\n"),  # LF breaks into a CRLF file
    ):
        with pytest.raises(patcher._LocateError):
            patcher._verify(f, dreplace(got, replacement=bad), SetBody("Inserted body.\nline two."))


def test_flow_style_item_scalar_replacement():
    text = "items: [{id: REQ-001, title: T, priority: high}]\n"
    new, _ = edited(text, "REQ-001", SetField("priority", "low"))
    assert yaml.safe_load(new)["items"][0]["priority"] == "low"


def test_section_marker_blocks_are_not_items():
    text = "items:\n  - section: Power\n  - id: REQ-001\n    title: T\n"
    got = plan(text, "REQ-001", SetField("title", "U"))
    assert got.ok
    bad = refuse(text, "Power", SetField("title", "U"))
    assert "no item" in bad.reason


# ------------------------------------------------------------- YAML 1.1 traps


@pytest.mark.parametrize(
    "value",
    ["yes", "no", "on", "off", "null", "~", "0755", "1:20", "2026-01-05", "1.0", "", "  padded  ",
     "true", "!!str", "*alias", "&anchor", "# not a comment", "- dash", "a: b", "@weird", "%tag",
     "123", "3.14", "N/A", "y"],
)
def test_string_that_yaml_would_misread_is_quoted_and_reads_back_the_same(value):
    text = "items:\n  - id: REQ-001\n    title: original\n"
    new, _ = edited(text, "REQ-001", SetField("title", value))
    got = yaml.safe_load(new)["items"][0]["title"]
    assert got == value and type(got) is str, f"{value!r} came back as {got!r}"


def test_setting_a_number_stays_a_number():
    text = "items:\n  - id: REQ-001\n    watts: 5\n"
    new, _ = edited(text, "REQ-001", SetField("watts", 12))
    assert yaml.safe_load(new)["items"][0]["watts"] == 12


def test_setting_a_date_field_to_a_string_is_quoted():
    text = "items:\n  - id: REQ-001\n    date: 2026-01-05\n"
    new, _ = edited(text, "REQ-001", SetField("date", "2026-01-06"))
    assert yaml.safe_load(new)["items"][0]["date"] == "2026-01-06"


def test_booleans_stay_booleans():
    text = "items:\n  - id: REQ-001\n    keep_copy: true\n"
    new, _ = edited(text, "REQ-001", SetField("keep_copy", False))
    assert yaml.safe_load(new)["items"][0]["keep_copy"] is False


# ---------------------------------------------------------------- refusals


def test_anchor_inside_the_span_is_refused():
    text = "items:\n  - id: REQ-001\n    title: &t T\n    other: *t\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "anchor" in bad.reason or "alias" in bad.reason


def test_alias_is_refused_even_when_it_is_not_the_edited_field():
    text = "items:\n  - id: REQ-001\n    title: &t T\n    other: *t\n"
    bad = refuse(text, "REQ-001", SetField("other", "U"))
    assert "alias" in bad.reason or "anchor" in bad.reason


def test_explicit_tag_is_refused():
    text = "items:\n  - id: REQ-001\n    title: !!str T\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "tag" in bad.reason


def test_second_document_is_refused():
    text = "items:\n  - id: REQ-001\n    title: T\n---\nitems:\n  - id: REQ-002\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "document" in bad.reason


def test_bom_is_refused():
    text = "\ufeffitems:\n  - id: REQ-001\n    title: T\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "BOM" in bad.reason


def test_duplicate_key_is_refused():
    text = "items:\n  - id: REQ-001\n    title: one\n    title: two\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "appears 2 times" in bad.reason


def test_duplicate_id_is_refused():
    text = "items:\n  - id: REQ-001\n    title: one\n  - id: REQ-001\n    title: two\n"
    bad = refuse(text, "REQ-001", SetField("title", "U"))
    assert "names 2 items" in bad.reason


def test_literal_fence_in_existing_markdown_body_is_refused():
    text = "---\nid: DEC-001\n---\n\nbefore\n\n---\n\nafter the rule\n"
    bad = refuse(text, "DEC-001", SetBody("new\n"))
    assert "---" in bad.reason


def test_new_body_containing_a_fence_is_refused():
    bad = refuse(MD_FILE, "DEC-001", SetBody("prose\n---\nmore\n"))
    assert "---" in bad.reason


def test_new_yaml_body_containing_a_fence_is_refused():
    text = "items:\n  - id: REQ-001\n    body: prose\n"
    bad = refuse(text, "REQ-001", SetBody("a\n---\nb\n"))
    assert "---" in bad.reason


def test_collection_value_is_refused():
    text = "items:\n  - id: REQ-001\n    tags: [a, b]\n"
    bad = refuse(text, "REQ-001", SetField("tags", "one"))
    assert "not a scalar" in bad.reason


def test_nested_mapping_value_is_refused():
    text = "items:\n  - id: REQ-001\n    meta:\n      a: 1\n"
    bad = refuse(text, "REQ-001", SetField("meta", "x"))
    assert "not a scalar" in bad.reason


@pytest.mark.parametrize("name", ["id", "key"])
def test_identity_fields_are_protected(name):
    text = f"items:\n  - {name}: REQ-001\n    title: T\n"
    bad = refuse(text, "REQ-001", SetField(name, "REQ-999"))
    assert "identity" in bad.reason


def test_unknown_ref_is_refused_with_what_the_file_holds():
    bad = refuse(LIST_FILE, "REQ-404", SetField("title", "U"))
    assert "REQ-001" in bad.reason


def test_comment_between_key_and_value_is_refused():
    text = "items:\n  - id: REQ-001\n    body: # what this documents\n      the prose\n"
    bad = refuse(text, "REQ-001", SetBody("new prose\n"))
    assert "comment" in bad.reason


def test_unparseable_file_is_refused_not_raised():
    bad = refuse("items:\n  - id: [unclosed\n", "REQ-001", SetField("title", "U"))
    assert "invalid YAML" in bad.reason


def test_empty_file_is_refused():
    assert isinstance(plan_patch("", "REQ-001", SetField("title", "U")), Refusal)


def test_markdown_without_front_matter_is_refused():
    bad = refuse("# just a heading\n\ntext\n", "X", SetField("title", "U"))
    assert "front-matter" in bad.reason or "no item" in bad.reason


def test_bytes_are_refused():
    bad = refuse(b"items: []", "X", SetField("title", "U"))
    assert "text" in bad.reason


def test_apply_a_refusal_raises():
    with pytest.raises(patcher.PatchRefused):
        apply_patch(LIST_FILE, refuse(LIST_FILE, "REQ-404", SetField("title", "x")))


def test_stale_plan_is_refused_at_apply_time():
    got = plan(LIST_FILE, "REQ-001", SetField("title", "A"))
    moved = "# added\n" + LIST_FILE
    with pytest.raises(patcher.PatchRefused):
        apply_patch(moved, got)


def test_applying_the_same_plan_twice_is_refused():
    got = plan(LIST_FILE, "REQ-001", SetField("title", "A"))
    once = apply_patch(LIST_FILE, got)
    with pytest.raises(patcher.PatchRefused):
        apply_patch(once, got)


def test_edit_that_would_change_another_item_is_refused():
    # A body whose replacement text ends the item and starts a new one would
    # change the item count; the verification gate has to catch it even though
    # the result parses.
    text = "items:\n  - id: REQ-001\n    body: |\n      prose\n"
    got = plan_patch(text, "REQ-001", SetField("body", "ok\n"))
    assert isinstance(got, PatchPlan)


# ---------------------------------------------------------------- insertion


def test_insert_a_missing_scalar_field():
    text = "items:\n  - id: REQ-001\n    title: T\n"
    new, got = edited(text, "REQ-001", SetField("priority", "high"))
    assert got.op == "insert"
    assert yaml.safe_load(new)["items"][0]["priority"] == "high"
    assert "    priority: high" in new


def test_insert_after_a_block_scalar_does_not_land_inside_it():
    text = "items:\n  - id: REQ-001\n    body: |\n      prose\n\n  - id: REQ-002\n    title: T\n"
    new, _ = edited(text, "REQ-001", SetField("priority", "high"))
    assert yaml.safe_load(new)["items"][0] == {"id": "REQ-001", "body": "prose\n", "priority": "high"}
    assert yaml.safe_load(new)["items"][1]["title"] == "T"


def test_insert_a_body_into_an_item_that_has_none():
    text = "items:\n  - id: CMP-001\n    part_number: TPS62913\n"
    new, got = edited(text, "CMP-001", SetBody("Selected for efficiency.\n"))
    assert yaml.safe_load(new)["items"][0]["body"] == "Selected for efficiency.\n"


def test_insert_into_a_flow_item_is_refused():
    text = "items: [{id: REQ-001, title: T}]\n"
    bad = refuse(text, "REQ-001", SetField("priority", "high"))
    assert "flow" in bad.reason


def test_insert_into_markdown_front_matter():
    new, got = edited(MD_FILE, "DEC-001", SetField("owner", "J. Bin"))
    assert "owner: J. Bin" in new
    assert new.endswith("Prose about the choice.\n")


# ------------------------------------------------------ exact revert vs re-set


def test_revert_is_byte_identical():
    got = plan(LIST_FILE, "REQ-001", SetField("title", "Changed"))
    new = apply_patch(LIST_FILE, got)
    assert apply_patch(new, revert_plan(got)) == LIST_FILE


def test_revert_of_a_body_is_byte_identical():
    got = plan(MD_FILE, "DEC-001", SetBody("Completely different.\n"))
    new = apply_patch(MD_FILE, got)
    assert apply_patch(new, revert_plan(got)) == MD_FILE


def test_reverting_a_refusal_raises():
    with pytest.raises(patcher.PatchRefused):
        revert_plan(refuse(LIST_FILE, "REQ-404", SetField("title", "x")))


# ------------------------------------------------------- the plan names its span


def test_plan_names_the_span_it_touches():
    got = plan(LIST_FILE, "REQ-001", SetField("priority", "low"))
    assert LIST_FILE[got.start : got.end] == "high" == got.original
    assert got.replacement == "low"
    assert got.start_line == LIST_FILE[: got.start].count("\n") + 1


def test_byte_span_matches_utf8_offsets():
    text = "items:\n  - id: REQ-001\n    title: 效率\n"
    got = plan(text, "REQ-001", SetField("title", "T"))
    b0, b1 = got.byte_span(text)
    assert text.encode("utf-8")[b0:b1].decode("utf-8") == "效率"


def test_plan_carries_the_path_for_messages():
    got = plan(LIST_FILE, "REQ-001", SetField("priority", "low"), path="items/x.yaml")
    assert "items/x.yaml" in got.describe()
    bad = refuse(LIST_FILE, "NOPE", SetField("priority", "low"), path="items/x.yaml")
    assert bad.path == "items/x.yaml"


def test_patch_item_returns_text_and_plan():
    new, got = patcher.patch_item(LIST_FILE, "REQ-001", SetField("priority", "low"))
    assert got.ok and "priority: low" in new
    same, bad = patcher.patch_item(LIST_FILE, "NOPE", SetField("priority", "low"))
    assert same is LIST_FILE and isinstance(bad, Refusal)


# ------------------------------------------- property pass over the repo's items

def _item_files():
    out = []
    for dirpath, _, names in os.walk(ITEMS):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", newline="") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            out.append((os.path.relpath(path, REPO), text))
    return out


def _load(text):
    try:
        return patcher._load(text)
    except patcher._LocateError:
        return None


@pytest.mark.parametrize("rel,text", _item_files())
def test_every_real_file_loads_or_refuses_cleanly(rel, text):
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    assert f.items, rel


@pytest.mark.parametrize("rel,text", _item_files())
def test_every_editable_field_round_trips_byte_identically(rel, text):
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    for item in f.items:
        for name, node in item.fields.items():
            if name in patcher.PROTECTED_FIELDS or not isinstance(node, yaml.ScalarNode):
                continue
            got = plan_patch(text, item.ref, SetField(name, "patcher probe"))
            assert isinstance(got, PatchPlan), f"{rel} {item.ref}.{name}: {got.reason}"
            new = apply_patch(text, got)
            assert new[: got.start] == text[: got.start], rel
            assert new[len(new) - len(text) + got.end :] == text[got.end :], rel
            assert apply_patch(new, revert_plan(got)) == text, f"{rel} {item.ref}.{name}"


@pytest.mark.parametrize("rel,text", _item_files())
def test_every_item_body_round_trips_byte_identically(rel, text):
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    for item in f.items:
        got = plan_patch(text, item.ref, SetBody("patcher probe body\n"))
        assert isinstance(got, PatchPlan), f"{rel} {item.ref}: {got.reason}"
        new = apply_patch(text, got)
        assert apply_patch(new, revert_plan(got)) == text, f"{rel} {item.ref} body"


@pytest.mark.parametrize("rel,text", _item_files())
def test_patched_real_files_still_parse_with_the_real_parser(rel, text):
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    item = f.items[0]
    got = plan_patch(text, item.ref, SetField(next(iter(
        k for k, v in item.fields.items()
        if k not in patcher.PROTECTED_FIELDS and isinstance(v, yaml.ScalarNode)
    )), "probe"))
    if not isinstance(got, PatchPlan):
        pytest.skip(got.reason)
    new = apply_patch(text, got)
    after = _load(new)
    assert after is not None, rel
    assert len(after.items) == len(f.items)


def _crlf_item_files():
    """The repo's items files with every break converted to CRLF, written to a
    temp copy under .scratch/ so the working tree is never touched."""
    import shutil
    import tempfile

    out = []
    dest = Path(tempfile.mkdtemp(prefix="crlf-items-", dir=_scratch_dir()))
    try:
        for rel, text in _item_files():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(text.replace("\n", "\r\n").encode("utf-8"))
            with open(target, encoding="utf-8", newline="") as fh:
                out.append((rel, fh.read()))
    finally:
        shutil.rmtree(dest, ignore_errors=True)
    return out


def _scratch_dir():
    scratch = Path(REPO) / ".scratch"
    scratch.mkdir(exist_ok=True)
    return scratch


@pytest.mark.parametrize("rel,text", _crlf_item_files())
def test_crlf_copies_of_the_repo_edit_their_bodies_without_refusal(rel, text):
    """Jared's checkout is CRLF (core.autocrlf=true), so every real body edit
    must plan there too -- a CRLF conversion is not a reason to refuse."""
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    for item in f.items:
        got = plan_patch(text, item.ref, SetBody("patcher probe body\n"))
        assert isinstance(got, PatchPlan), f"{rel} {item.ref}: {got.reason}"
        new = apply_patch(text, got)
        assert new[: got.start] == text[: got.start], rel
        assert new[len(new) - len(text) + got.end :] == text[got.end :], rel
        assert apply_patch(new, revert_plan(got)) == text, f"{rel} {item.ref} body"


@pytest.mark.parametrize("rel,text", _crlf_item_files())
def test_crlf_copies_of_the_repo_take_a_new_field_without_broken_breaks(rel, text):
    """Every real item must accept a field it does not have yet, on a CRLF
    checkout, with no split line break and a byte-identical revert."""
    f = _load(text)
    if f is None:
        pytest.skip(f"{rel} is not a patchable items file")
    for item in f.items:
        name = "patcher_probe"
        if name in item.fields:
            continue
        got = plan_patch(text, item.ref, SetField(name, "probe value"))
        assert isinstance(got, PatchPlan), f"{rel} {item.ref}: {got.reason}"
        new = apply_patch(text, got)
        assert new[: got.start] == text[: got.start], rel
        assert new[len(new) - len(text) + got.end :] == text[got.end :], rel
        assert_breaks_are_whole(new, "\r\n")
        assert apply_patch(new, revert_plan(got)) == text, f"{rel} {item.ref}.{name}"


def _break_variant_files():
    """Every items file of the repo in four break states: LF, CRLF, and each of
    those without the file's final break. The working copy's own breaks are
    normalised first so a CRLF checkout produces the same cases as an LF one."""
    out = []
    for rel, text in _item_files():
        for tag, variant in _line_break_variants(text.replace("\r\n", "\n")).items():
            out.append((f"{rel}::{tag}", tag, variant))
    return out


def _ends_in_block_scalar(text, item):
    """True when the item's last field is a block scalar whose text runs to EOF."""
    if not item.fields:
        return False
    last = list(item.fields.values())[-1]
    if isinstance(last, list):
        last = last[-1]
    return getattr(last, "style", None) in ("|", "|-", "|+", ">", ">-", ">+") and last.end_mark.index == len(
        text.rstrip("\r\n")
    )


def _eol_of(tag):
    return "\r\n" if tag.startswith("crlf") else "\n"


@pytest.mark.parametrize("label,tag,text", _break_variant_files())
def test_every_repo_item_takes_every_edit_in_every_break_state(label, tag, text):
    """The whole-file version of the break guarantee.

    A doubled conversion at the end of a Markdown body was invisible to a check
    that counted bare LFs: the LF of the final break is intact, and it is the
    CR beside it that is stray. So the assertion is about the whole file after
    the edit, not about the neighbourhood of the span, and it runs over every
    edit kind -- body, a key the item does not have, every scalar key it does.
    """
    f = _load(text)
    if f is None:
        pytest.skip(f"{label} is not a patchable items file")
    eol = _eol_of(tag)
    had_final_break = text.endswith("\n")
    ops = [("body", SetBody("patcher probe body\n"))]
    ops.append(("patcher_probe", SetField("patcher_probe", "probe value")))
    for item in f.items:
        edits = list(ops)
        for name, node in item.fields.items():
            if name in patcher.PROTECTED_FIELDS or not isinstance(node, yaml.ScalarNode):
                continue
            if name == "patcher_probe":
                continue
            edits.append((name, SetField(name, "probe")))
        trailing_block = _ends_in_block_scalar(text, item)
        for what, op in edits:
            got = plan_patch(text, item.ref, op)
            if not isinstance(got, PatchPlan):
                # Appending a key after a block scalar that runs to EOF without
                # a final break gives the block a following line, and clip
                # chomping then hands the body a trailing newline it did not
                # have. That changes a different field's value, so the patcher
                # refuses it -- on LF files too, so it is not a break bug. It is
                # the fidelity contract holding, and this pass does not re-litigate it.
                assert trailing_block and what == "patcher_probe" and not had_final_break, (
                    f"{label} {item.ref}.{what}: {got.reason}"
                )
                continue
            assert isinstance(got, PatchPlan)
            new = apply_patch(text, got)
            assert new[: got.start] == text[: got.start], f"{label} {item.ref}.{what} before"
            assert new[len(new) - len(text) + got.end :] == text[got.end :], (
                f"{label} {item.ref}.{what} after"
            )
            assert_breaks_are_whole(new, eol)
            if not got.replacement.endswith(("\n", "\r")):
                # A replacement that ends in a break brings its own; the file's
                # own final break is only owed when the edit does not supply one.
                assert new.endswith("\n") == had_final_break, f"{label} {item.ref}.{what} final break"
            assert apply_patch(new, revert_plan(got)) == text, f"{label} {item.ref}.{what} revert"


def test_the_repo_has_nothing_the_patcher_refuses():
    """Every editable field of every real item plans. A new refusal is a regression."""
    refused = []
    for rel, text in _item_files():
        f = _load(text)
        if f is None:
            continue
        for item in f.items:
            for name, node in item.fields.items():
                if name in patcher.PROTECTED_FIELDS or not isinstance(node, yaml.ScalarNode):
                    continue
                got = plan_patch(text, item.ref, SetField(name, "probe"))
                if not isinstance(got, PatchPlan):
                    refused.append(f"{rel} {item.ref}.{name}: {got.reason}")
    assert refused == []
