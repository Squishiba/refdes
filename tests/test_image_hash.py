"""Image bytes as content: HASH_FORMAT 5 (docs/design/editor-image-upload.md
§15.6, decided by Jared; plan in in-prog-logs/hash-images.md).

The bytes of the images an item references enter its content hash, so a
swapped image is loud for sealed/baselined entries instead of silent. The
invariants pinned here, in the sabotage-paired style of
tests/test_calc_block_hash.py:

- an image-free item's format-5 payload is its format-4 payload, so the bump
  moves zero existing hashes;
- changing image bytes moves the owner's hash under format 5 and not under
  format 4 reconstructions;
- resolution mirrors `_process_images` (relative-first, bare-name search,
  ambiguity/unresolved -> a `[src, None]` sentinel beside the build error);
- a seal recorded under format 4 survives the bump even when the image bytes
  moved (the grandfathering the old record forces), and after the upgrade to
  format 5 an image change is a seal violation.

No hash literal is pinned anywhere: expected image digests are computed in
test over the bytes the test itself wrote (`wb`, line-ending independent),
and everything else is a moves/does-not-move relationship.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

from conftest import write_project_config
from helpers import _build_and_render

from refdes import build as build_mod
from refdes import keys, parse, seal
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision: { prefix: DEC, fields: {} }\n"
)

SEALED_CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  log:\n"
    "    prefix: LOG\n"
    "    append_only: true\n"
    "    fields: {}\n"
    "  note:\n"
    "    prefix: NOTE\n"
    "    fields: {}\n"
    "    body: { on_change: ignore }\n"
)

PNG_A = b"\x89PNG\r\n\x1a\nfirst bytes"
PNG_B = b"\x89PNG\r\n\x1a\nsecond bytes"
PNG_C = b"\x89PNG\r\n\x1a\nthird bytes"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _item(item_id: str, body: str, type_: str = "decision") -> str:
    return f"---\nid: {item_id}\ntype: {type_}\n---\n\n{body}"


def _build(tmp_path, files: dict[str, str], binaries: dict[str, bytes],
           config: str = CONFIG):
    write_project_config(tmp_path, config)
    for name, text in files.items():
        path = tmp_path / "items" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name, data in binaries.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    if keys.mint_missing(project, write=True):
        project.items = {}
        project.items_by_id = {}
        project.pending = []
        parse.load_items(project)
    build_mod.build(project)
    return project


def _rebuild(tmp_path):
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    build_mod.build(project)
    return project


def _payload(project, item, fmt=None):
    fmt = build_mod.HASH_FORMAT if fmt is None else fmt
    return build_mod.hash_payload_builder(project, fmt)(
        item, project.types[item.type]
    )


def _write_image(tmp_path, name: str, data: bytes) -> None:
    (tmp_path / name).write_bytes(data)


def test_image_free_item_payload_is_its_format_4_payload(tmp_path):
    """The no-churn guarantee: format 5 adds an `images` key only for bodies
    that reference images, so the bump moves no existing hash. Sabotage: a
    format-5 builder that always writes `images` (even empty), or that looks
    at anything besides image references, fails here."""
    p = _build(tmp_path, {
        "a.md": _item("DEC-001", "prose, no images\n"),
        "b.md": _item("DEC-002", "```calc\nV_in = 12 V\n```\n"),
    }, {})
    assert not p.errors, p.errors
    for item in p.local_items:
        assert "images" not in _payload(p, item)
        assert _payload(p, item) == _payload(p, item, 4)
        assert item.content_hash == build_mod.hash_for_format(item, p, 4)


def test_image_bytes_move_owner_hash_under_5_not_4(tmp_path):
    """The bump itself: identical item text, image bytes swapped -- the
    format-5 content_hash moves, the format-4 reconstruction does not.
    Sabotage: images gated at >= 4 (the old hash would move too) or >= 6
    (nothing moves); either fails here."""
    p1 = _build(tmp_path, {"a.md": _item("DEC-001", "![curve](curve.png)\n")},
                {"items/curve.png": PNG_A})
    assert not p1.errors, p1.errors
    item1 = p1.item_by_id("DEC-001")
    hash5_v1 = item1.content_hash
    hash4_v1 = build_mod.hash_for_format(item1, p1, 4)
    assert _payload(p1, item1)["images"] == [["items/curve.png", _digest(PNG_A)]]
    # the digest is the same one the render pass splices into the asset leaf
    assert p1.assets["items/curve.png"] == f"items/curve.{_digest(PNG_A)}.png"

    _write_image(tmp_path, "items/curve.png", PNG_B)
    p2 = _rebuild(tmp_path)
    assert not p2.errors, p2.errors
    item2 = p2.item_by_id("DEC-001")
    assert item2.content_hash != hash5_v1, "image bytes are content under 5"
    assert _payload(p2, item2)["images"] == [["items/curve.png", _digest(PNG_B)]]
    assert build_mod.hash_for_format(item2, p2, 4) == hash4_v1, (
        "format 4 must keep reconstructing the pre-bump hash, images or not"
    )


def test_images_payload_is_sorted_deduped_and_skips_urls(tmp_path):
    """Shape: one entry per distinct resolved file, sorted by project-relative
    path; the same image twice contributes once; URL srcs contribute nothing.
    Sabotage: document order, or counting the same file twice, or hashing a
    URL's text as if it resolved."""
    body = (
        "![b](img2.png)\n\n"
        "![a](img1.png)\n\n"
        "![a again](img1.png)\n\n"
        "![ext](https://example.com/x.png)\n"
    )
    p = _build(tmp_path, {"a.md": _item("DEC-001", body)},
               {"items/img1.png": PNG_A, "items/img2.png": PNG_B})
    assert not p.errors, p.errors
    assert _payload(p, p.item_by_id("DEC-001"))["images"] == [
        ["items/img1.png", _digest(PNG_A)],
        ["items/img2.png", _digest(PNG_B)],
    ]


def test_shared_image_moves_exactly_its_referencing_items(tmp_path):
    """Blast radius: two items reference one image -- both hashes move when
    its bytes change, the third item's does not. Sabotage: a digest cache
    keyed by item instead of by path (one owner left behind), or a global
    seed (the bystander moves too)."""
    files = {
        "a.md": _item("DEC-001", "![s](shared.png)\n"),
        "b.md": _item("DEC-002", "![s too](shared.png)\n"),
        "c.md": _item("DEC-003", "no images here\n"),
    }
    p1 = _build(tmp_path, files, {"items/shared.png": PNG_A})
    assert not p1.errors, p1.errors
    before = {i.id: i.content_hash for i in p1.local_items}

    _write_image(tmp_path, "items/shared.png", PNG_B)
    p2 = _rebuild(tmp_path)
    assert not p2.errors, p2.errors
    after = {i.id: i.content_hash for i in p2.local_items}
    assert after["DEC-001"] != before["DEC-001"]
    assert after["DEC-002"] != before["DEC-002"]
    assert after["DEC-003"] == before["DEC-003"], "no image, no move"


def test_missing_image_contributes_sentinel_and_still_errors(tmp_path):
    """An unresolved src contributes `[raw src, None]` -- deterministic and
    distinct from any real pair -- and the existing build error is unchanged.
    Sabotage: raising from the hash pass (double diagnostic, and a crash
    before the render pass can report), or contributing nothing (a missing
    image would hash like no images at all)."""
    p = _build(tmp_path, {"a.md": _item("DEC-001", "![x](figures/nope.png)\n")},
               {})
    assert any("does not exist" in d.message for d in p.errors), p.errors
    assert _payload(p, p.item_by_id("DEC-001"))["images"] == [
        ["figures/nope.png", None]
    ]


def test_ambiguous_bare_src_contributes_sentinel_and_still_errors(tmp_path):
    """Two matches on the search path: the ambiguity build error stands, and
    the hash contribution is the same `[raw src, None]` sentinel -- the hash
    pass shares `_search_image_src`'s search without duplicating its
    diagnostics. Sabotage: a first-match pick in the hash pass (silent
    divergence from the erroring render pass)."""
    config = (
        "site: { title: T, out: _site, assets: [figures/a, figures/b] }\n"
        "types:\n  decision: { prefix: DEC, fields: {} }\n"
    )
    p = _build(tmp_path, {"a.md": _item("DEC-001", "![x](x.png)\n")},
               {"figures/a/x.png": PNG_A, "figures/b/x.png": PNG_B},
               config=config)
    assert any("ambiguous" in d.message for d in p.errors), p.errors
    assert _payload(p, p.item_by_id("DEC-001"))["images"] == [["x.png", None]]


def test_unresolved_text_equal_to_resolved_path_sorts_and_hashes(tmp_path):
    """IMAGE-ASSET-001: a raw unresolved-with-separator src whose text equals
    another src's resolved project-relative path puts `[path, None]` and
    `[path, digest]` in one set, so sorting the raw pairs compared the ``None``
    sentinel with a str digest and raised TypeError -- crashing the whole hash
    pass, and the build, before the render pass could report the missing image.
    Sabotage: sort the pairs themselves (the crash); or sort by `str(pair)`,
    which survives but orders the sentinel by the text `'None'`, after every
    digest -- an order nobody chose; or return the set unsorted (the forced
    seed sweep below then disagrees with the in-process hash)."""
    expected = [
        ["assets/sub/img.png", None],
        ["assets/sub/img.png", _digest(PNG_A)],
    ]
    unresolved_first = (
        "![bare-rel](assets/sub/img.png)\n\n"
        "![resolved](../assets/sub/img.png)\n"
    )
    resolved_first = (
        "![resolved](../assets/sub/img.png)\n\n"
        "![bare-rel](assets/sub/img.png)\n"
    )
    for body in (unresolved_first, resolved_first):
        p = _build(tmp_path, {"a.md": _item("DEC-001", body)},
                   {"assets/sub/img.png": PNG_A})
        assert any("does not exist" in d.message for d in p.errors), (
            "the build must report the unresolved src, not crash: " + str(p.errors)
        )
        assert _payload(p, p.item_by_id("DEC-001"))["images"] == expected

    p = _build(tmp_path, {"a.md": _item("DEC-001", unresolved_first)},
               {"assets/sub/img.png": PNG_A})
    expected_hash = p.item_by_id("DEC-001").content_hash
    # The set-iteration proof proper: recompute the same item's hash in
    # subprocesses with forced PYTHONHASHSEED values. str hashing is
    # randomized per process, so a two-entry set can iterate in either
    # order run to run; if the hash contribution's order came from the set
    # rather than the sort key, different seeds would produce different
    # hashes. Sabotage: return list(entries) unsorted -- the seeds disagree.
    script = (
        "import sys\n"
        "from refdes import build as b, parse\n"
        "from refdes.schema import load_project\n"
        "pr = load_project(config_path=sys.argv[1])\n"
        "parse.load_items(pr)\n"
        "b.compute_hashes(pr)\n"
        "print(pr.item_by_id('DEC-001').content_hash)\n"
    )
    src_dir = os.path.dirname(os.path.dirname(build_mod.__file__))
    for seed in ("0", "1", "42"):
        env = dict(os.environ, PYTHONPATH=src_dir, PYTHONHASHSEED=seed)
        result = subprocess.run(
            [sys.executable, "-c", script,
             str(tmp_path / "refdes-project.yaml")],
            capture_output=True, text=True, check=True, env=env,
        )
        assert result.stdout.strip() == expected_hash, f"seed {seed} diverged"


def test_image_in_code_fence_contributes_nothing(tmp_path):
    """The hash pass parses with the render pass's markdown-it config, so an
    image inside a code fence -- which never renders as an image -- never
    contributes. Sabotage: a regex scan of raw body text, which would count
    the fenced one and move the hash for bytes that render nowhere."""
    body = "example only:\n\n```\n![x](ghost.png)\n```\n"
    p = _build(tmp_path, {"a.md": _item("DEC-001", body)}, {})
    assert not p.errors, p.errors
    assert "images" not in _payload(p, p.item_by_id("DEC-001"))


def test_body_not_invalidating_has_no_images_key(tmp_path):
    """`images` rides the body's on_change: a type whose body is `ignore`
    drags no image digests into the payload, and its image bytes cannot move
    its hash. Sabotage: contributing images outside the INVALIDATE branch."""
    p = _build(tmp_path, {"a.md": _item("NOTE-001", "![s](s.png)\n", "note")},
               {"items/s.png": PNG_A}, config=SEALED_CONFIG)
    assert not p.errors, p.errors
    item1 = p.item_by_id("NOTE-001")
    assert "images" not in _payload(p, item1)
    h1 = item1.content_hash
    _write_image(tmp_path, "items/s.png", PNG_B)
    p2 = _rebuild(tmp_path)
    assert p2.item_by_id("NOTE-001").content_hash == h1


def test_calc_hash_is_unmoved_by_image_bytes(tmp_path):
    """calc_hash_for asks the stale-arithmetic question -- block source text
    -- and an image swap is not arithmetic. Sabotage: folding image digests
    into calc_hash_for instead of content_hash."""
    body = "```calc\nV_in = 12 V\n```\n\n![curve](curve.png)\n"
    p1 = _build(tmp_path, {"a.md": _item("DEC-001", body)},
                {"items/curve.png": PNG_A})
    owner1 = p1.item_by_id("DEC-001")
    calc_hash = build_mod.calc_hash_for(owner1)
    content1 = owner1.content_hash
    assert calc_hash is not None

    _write_image(tmp_path, "items/curve.png", PNG_B)
    p2 = _rebuild(tmp_path)
    owner2 = p2.item_by_id("DEC-001")
    assert build_mod.calc_hash_for(owner2) == calc_hash
    assert owner2.content_hash != content1


def test_format4_seal_survives_bump_then_image_change_is_loud(tmp_path):
    """The seal-sensitive contract, end to end:

    1. a seal recorded under format 4 verifies after the bump even though the
       image bytes moved since -- formats <= 4 reconstruct without images, so
       the bump itself never makes a sealed entry look edited, and an older
       image change is grandfathered (the old record never stored a digest;
       there is nothing to compare). Pinned so the behavior is owned, not
       accidental.
    2. a writable build upgrades the seal to format 5 with the current digest.
    3. from then on an image byte change is a seal violation -- the loudness
       §15.6 was about.
    """
    files = {"a.md": _item("LOG-001", "![curve](curve.png)\n", "log")}
    p1 = _build(tmp_path, files, {"items/curve.png": PNG_A},
                config=SEALED_CONFIG)
    assert not p1.errors, p1.errors
    item1 = p1.item_by_id("LOG-001")
    hash4 = build_mod.hash_for_format(item1, p1, 4)
    assert hash4 != item1.content_hash, "with an image, 4 and 5 differ"
    seal.save_seals(p1, {"LOG-001": {"hash": hash4, "hash_format": 4}})

    # 1. image bytes move; the format-4 seal still verifies, read-only.
    _write_image(tmp_path, "items/curve.png", PNG_B)
    p2 = _rebuild(tmp_path)
    assert p2.seal_violations == [], "the bump must not break an old seal"
    assert not [e for e in p2.errors if "sealed" in e], p2.errors

    # 2. a writable build carries the seal forward to format 5.
    p3 = _rebuild(tmp_path)
    build_mod.compute_hashes(p3)
    seal.verify(p3, write=True)
    stored = seal.load_seals(p3)
    assert stored["LOG-001"]["hash_format"] == build_mod.HASH_FORMAT
    assert stored["LOG-001"]["hash"] == p3.item_by_id("LOG-001").content_hash

    # 3. now an image swap is loud.
    _write_image(tmp_path, "items/curve.png", PNG_C)
    p4 = _rebuild(tmp_path)
    assert p4.seal_violations == ["LOG-001"]
    assert any(
        "modified since it was sealed" in d.message for d in p4.errors
    ), p4.errors


# ------------------------------------------------- one canonical src (IMAGE-ASSET-002)


def test_src_with_ampersand_resolves_in_both_passes_and_publishes(tmp_path):
    """One image, one spelling of its name. The hash pass reads the raw
    markdown-it token src; the render pass scans the rendered HTML, where the
    renderer has escaped `&` to `&amp;` inside the attribute. Resolving the
    escaped spelling (the finding) made the build error on and fail to publish
    an image its own content hash had already recorded. Sabotage: resolve the
    raw attribute in the render pass (the finding returns); decode with
    `html.unescape` (over-decodes a filename that literally carries `&amp;`
    -- the test below); percent-decode on top (the documented
    `figures/thermal%20curve.png` lookup miss becomes a hit the picker's
    contract never promised)."""
    p = _build(tmp_path, {"a.md": _item("DEC-001", "![board](a&b.png)\n")},
               {"items/a&b.png": PNG_A})
    assert not p.errors, p.errors
    digest = _digest(PNG_A)
    assert _payload(p, p.item_by_id("DEC-001"))["images"] == [
        ["items/a&b.png", digest]
    ]
    # the published page spells the src the way the renderer spells it -- a
    # browser decodes `&amp;` back to the real asset filename
    assert (
        f'src="assets/items/a&amp;b.{digest}.png"' in p.item_by_id("DEC-001").body_html
    )
    out = _build_and_render(tmp_path)
    published = os.path.join(out, "assets", "items", f"a&b.{digest}.png")
    assert os.path.isfile(published)
    with open(published, "rb") as fh:
        assert fh.read() == PNG_A


def test_literal_amp_entity_in_a_filename_round_trips(tmp_path):
    """`![x](a&amp;amp;b.png)` parses to the token src `a&amp;b.png` -- a file
    whose name literally carries the four characters `&amp;` -- and the
    attribute carries it escaped once more, as `&amp;amp;`. The render pass
    decodes exactly one entity layer and lands on the real file; a decoder
    that keeps decoding lands on `a&b.png`, which is not this file. The hash
    contribution is the token spelling, so hash and published leaf agree
    there too."""
    p = _build(tmp_path, {"a.md": _item("DEC-001", "![x](a&amp;amp;b.png)\n")},
               {"items/a&amp;b.png": PNG_A})
    assert not p.errors, p.errors
    digest = _digest(PNG_A)
    assert _payload(p, p.item_by_id("DEC-001"))["images"] == [
        ["items/a&amp;b.png", digest]
    ]
    assert (
        f'src="assets/items/a&amp;amp;b.{digest}.png"'
        in p.item_by_id("DEC-001").body_html
    )
    out = _build_and_render(tmp_path)
    assert os.path.isfile(os.path.join(out, "assets", "items", f"a&amp;b.{digest}.png"))


def test_url_with_ampersand_is_untouched_by_the_canonicalisation(tmp_path):
    """Scheme srcs skip resolution in both passes -- on the canonical
    spelling, where the scheme is visible before any escaping. Sabotage:
    canonicalise after the scheme test, or feed a URL through the resolver
    (an `assets/https:/...` rewrite of an external image)."""
    p = _build(
        tmp_path,
        {"a.md": _item("DEC-001", "![x](https://example.com/a&b.png)\n")},
        {},
    )
    assert not p.errors, p.errors
    item = p.item_by_id("DEC-001")
    assert 'src="https://example.com/a&amp;b.png"' in item.body_html
    assert p.assets == {}
    assert "images" not in _payload(p, item)


def test_recorded_src_is_the_spelling_the_filesystem_uses(tmp_path):
    """`Project.image_results` answers upload.py's capture check ("would
    landing this file re-point that reference?") by comparing the recorded
    src to a *filesystem* leaf, and serve's preview decoration by comparing
    published attributes to recorded srcs. Both questions are about the
    authored spelling; at the finding the record carried the HTML-escaped
    one, and a reference to `a&b.png` answered to neither. Sabotage: record
    the raw attribute (the escaped spelling leaks into the upload check)."""
    p = _build(tmp_path, {"a.md": _item("DEC-001", "![board](a&b.png)\n")},
               {"items/a&b.png": PNG_A})
    assert not p.errors, p.errors
    (record,) = p.image_results["DEC-001"]
    assert record["ok"] is True
    assert record["src"] == "a&b.png"
    assert record["rel"] == "items/a&b.png"
    assert record["dest"] == f"items/a&b.{_digest(PNG_A)}.png"
