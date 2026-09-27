"""Static checks on the served editor (docs/design/browser-editor.md, Security
and "No Node build step"): the shell is packaged plain ES modules under a CSP of
`script-src 'self'`, so anything inline is both a CSP violation and a hole.

No browser here, so these are text checks over the files the server serves:
no inline script or inline event handler anywhere in the shell, no `eval` or
`new Function`, and every module the shell loads (directly or by import) exists.
"""

from __future__ import annotations

import os
import re

import pytest

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)

INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""from\s+['"]([^'"]+\.js)['"]""")
HTML_ASSET = re.compile(r"""(?:src|href)\s*=\s*["']/edit/static/([^"']+)["']""")
SCRIPT_WITHOUT_SRC = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)


def js_files():
    return sorted(n for n in os.listdir(STATIC) if n.endswith(".js"))


@pytest.mark.parametrize("name", js_files())
def test_no_inline_handlers_or_dynamic_code_in_served_js(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        text = fh.read()
    assert not INLINE_HANDLER.search(text), f"{name}: an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(text), f"{name}: no eval/new Function in the editor"
    assert "javascript:" not in text


def test_the_shell_has_no_inline_script_or_handler():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert not SCRIPT_WITHOUT_SRC.search(html), "index.html may only load scripts by src"
    assert not INLINE_HANDLER.search(html)
    assert "javascript:" not in html


def test_every_asset_the_shell_loads_exists():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    named = set(HTML_ASSET.findall(html))
    assert named, "index.html should reference its own static assets"
    for name in named:
        assert os.path.isfile(os.path.join(STATIC, name)), f"index.html loads a missing file: {name}"


def test_every_module_import_resolves():
    """The import graph, walked from what index.html loads: a typo'd module name
    is a blank page in the browser and nothing else would notice."""
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        entry = {n for n in HTML_ASSET.findall(fh.read()) if n.endswith(".js")}
    # preview.js is an entry too: injected into preview pages by the server's
    # decoration rather than referenced by index.html.
    entry.add("preview.js")
    assert entry
    seen = set()
    while entry:
        name = entry.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(STATIC, name)
        assert os.path.isfile(path), f"the editor imports a module that does not exist: {name}"
        with open(path, encoding="utf-8") as fh:
            for target in JS_IMPORT.findall(fh.read()):
                if target.startswith("./"):
                    entry.add(target[2:])
                else:
                    entry.add(target)


def test_served_js_parses_as_es2020_modules():
    """No Node here, so the cheapest real check: every module's braces, parens
    and brackets balance and no `const`/`let` is declared twice in the same
    top-level scope -- the class of mistake that turns a module into a blank
    page with one console line."""
    for name in js_files():
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            text = fh.read()
        depth = {"(": ")", "[": "]", "{": "}"}
        stack = []
        in_string = None
        escaped = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_string:
                    in_string = None
                continue
            if ch in "'\"`":
                in_string = ch
            elif ch in depth:
                stack.append(depth[ch])
            elif stack and ch in ")]}":
                assert stack.pop() == ch, f"{name}: unbalanced {ch}"
        assert not stack, f"{name}: unclosed {stack}"
        top = re.findall(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", text, re.MULTILINE)
        assert len(top) == len(set(top)), f"{name}: duplicate top-level declaration in {name}"


# ------------------------------------------------------------ link pickers


def test_the_link_picker_is_wired_into_the_editor():
    """Slice 2's UI has to actually reach the page: links.js must exist, be
    imported by editor.js (the import-graph walk above proves it resolves),
    and the save path must know the two link ops. A picker nothing imports
    is a picker nobody sees."""
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './links.js'" in editor
    assert "createLinksSection" in editor
    assert "'add_link'" in editor and "'remove_link'" in editor
    assert os.path.isfile(os.path.join(STATIC, "links.js"))


def test_the_link_draft_rides_the_one_draft_mechanism():
    """Link adds/removes are draft ops in the same draft as fields and the
    body -- the design forbids a second draft mechanism."""
    with open(os.path.join(STATIC, "drafts.js"), encoding="utf-8") as fh:
        drafts = fh.read()
    assert "links: { add: {}, remove: {} }" in drafts
    assert "draftLinkAdd" in drafts and "draftLinkRemove" in drafts
    # and the picker sends handles, never a composite it invented itself
    with open(os.path.join(STATIC, "links.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "draftLinkAdd(handle, verb, row.handle || row.id)" in picker
    # the picker never builds a DISPLAY-ID@key composite itself: the service
    # owns that spelling, so the client must not even look like it does
    assert "@${" not in picker


# ------------------------------------------------------------- creation UI


def test_the_new_item_form_is_wired_into_the_shell():
    """Slice 3's UI has to actually reach the page: create.js must exist, be
    imported by app.js, be routed at #/new, and be offered by the nav. A form
    nothing routes to is a form nobody sees."""
    assert os.path.isfile(os.path.join(STATIC, "create.js"))
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "from './create.js'" in app
    assert "#/new" in app
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'href="#/new"' in html


def test_the_create_form_asks_the_server_and_never_mints():
    """The id the form shows is the server's pure plan (preview reserves
    nothing), submission goes to the one create endpoint, and the client never
    builds a composite or a key -- the same posture as the link picker."""
    with open(os.path.join(STATIC, "create.js"), encoding="utf-8") as fh:
        create = fh.read()
    assert "/api/create/schema" in create
    assert "/api/create/preview" in create
    assert "/api/items/create" in create
    assert "@${" not in create


def test_the_field_controls_are_shared_not_duplicated():
    """editor.js and create.js must build field controls from the same code:
    the design says the create form reuses the editor's controls, and a second
    copy is exactly the drift the reuse was meant to prevent."""
    assert os.path.isfile(os.path.join(STATIC, "controls.js"))
    for name in ("editor.js", "create.js"):
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            text = fh.read()
        assert "from './controls.js'" in text, f"{name} must use the shared controls"
        assert "fieldControlNode" in text
    with open(os.path.join(STATIC, "controls.js"), encoding="utf-8") as fh:
        controls = fh.read()
    assert "export function fieldControlNode" in controls


# ------------------------------------------------- preview auto-reload (W1)


def test_the_preview_page_carries_a_self_reload_probe():
    """Thread workbench W1: a served preview page must ship the polling
    probe, and the probe must follow the house pattern -- poll
    /api/revision and reload when the serial moves, importing the shared
    api.js rather than inventing a second transport or a push channel."""
    assert os.path.isfile(os.path.join(STATIC, "preview.js"))
    with open(os.path.join(STATIC, "preview.js"), encoding="utf-8") as fh:
        preview = fh.read()
    assert "from './api.js'" in preview
    assert "/api/revision" in preview
    assert "location.reload()" in preview
    assert "refdes-serial" in preview


def test_the_server_injects_the_probe_into_preview_responses():
    """The probe is decoration: the server injects the serial it rendered
    and the probe script into the HTTP response, like the toolbar."""
    server = os.path.join(
        os.path.dirname(STATIC), "server.py"
    )
    with open(server, encoding="utf-8") as fh:
        text = fh.read()
    assert 'name="refdes-serial"' in text
    assert "/edit/static/preview.js" in text


def test_the_calc_value_toggle_is_wired_without_inline_script():
    """Thread workbench W3: the show-values toggle is a plain button the
    server injects into calc tables and a listener in preview.js -- CSP is
    script-src 'self', so an inline onclick would silently do nothing."""
    with open(os.path.join(STATIC, "preview.js"), encoding="utf-8") as fh:
        preview = fh.read()
    assert "refdes-values-toggle" in preview
    assert "refdes-values-off" in preview
    assert "addEventListener" in preview
    server = os.path.join(os.path.dirname(STATIC), "server.py")
    with open(server, encoding="utf-8") as fh:
        text = fh.read()
    assert 'class="refdes-values-toggle"' in text
    assert "data-refdes-calc" in text
    # the injected button carries no handler attribute of its own
    assert "onclick" not in text


def test_the_item_view_offers_a_link_to_its_preview_page():
    """Thread workbench W1: from /edit/ the author can open the item's own
    /preview/ page -- the link is built from the server-provided `page`,
    never a slug the client guesses."""
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "Open preview" in item
    assert "/preview/${encodeURIComponent(item.page)}" in item
    assert "'_blank'" in item


# ------------------------------------------------- rebuild focus preservation


def test_the_rebuild_updates_controls_instead_of_replacing_them():
    """The focus-loss fix (in-prog-logs/browser-editor-edit-ui.md, "Focus is
    lost"): a revision-triggered re-render must carry controls over by field
    identity instead of tearing them down. Static checks: the pure update
    helpers exist in update.js (focus and selection captured and restored),
    item.js wires them around the re-render, and the controls carry a stable
    data-edit-key so identity survives the rebuild."""
    assert os.path.isfile(os.path.join(STATIC, "update.js"))
    with open(os.path.join(STATIC, "update.js"), encoding="utf-8") as fh:
        update = fh.read()
    for fn in (
        "export function captureFocus",
        "export function restoreFocus",
        "export function collectControls",
    ):
        assert fn in update, f"update.js is missing {fn}"
    assert "data-edit-key" in update
    # the caret travels too, not just focus
    assert "selectionStart" in update and "setSelectionRange" in update

    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "from './update.js'" in item
    assert "captureFocus(container)" in item
    # focus is captured before the container is cleared and restored after
    # the whole view (including the preview section) is rebuilt
    assert item.index("captureFocus(container)") < item.index("restoreFocus(container, focus)")
    assert item.index("restoreFocus(container, focus)") > item.rindex("container.textContent = ''")
    # controls are carried into the new render by field identity
    assert "controls.get(`field:${name}`)" in item
    assert "editor.bodyControl(item.body, controls.get('body'))" in item


def test_a_carried_over_control_is_rebound_not_double_bound():
    """Reusing a control node across a re-render is only correct if the old
    change handler is detached first (otherwise one keystroke writes the
    draft twice through two closures) and the value is written only when it
    differs (otherwise a rebuild fights the author's typing)."""
    with open(os.path.join(STATIC, "controls.js"), encoding="utf-8") as fh:
        controls = fh.read()
    assert "export function applyControl" in controls
    assert "removeEventListener" in controls
    assert "if (node.value !== shown)" in controls
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './controls.js'" in editor and "applyControl" in editor
    # the body textarea follows the same in-place rule
    assert "if (area.value !== shown)" in editor
    assert "area.removeEventListener" in editor


def test_a_sealed_log_offers_the_amend_flow():
    """"Amend this sealed log" links to a pre-filled create form: the
    correction is a new entry, so the affordance must exist on the sealed
    item and must route to creation, not pretend to edit the sealed entry."""
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "Amend this sealed log" in item
    assert "#/new?type=" in item
    assert "amends=" in item


# ------------------------------------------------------------- image picker


def test_the_image_picker_is_wired_into_the_body():
    """Phase 0's UI has to actually reach the page: images.js must exist, be
    imported by editor.js (the import-graph walk above proves it resolves), and
    be placed in the Body section by item.js, under the textarea it writes
    into. A picker nothing renders is a picker nobody sees."""
    assert os.path.isfile(os.path.join(STATIC, "images.js"))
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './images.js'" in editor
    assert "createImagePicker" in editor
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "editor.imagePicker" in item
    # it is placed beside the body control, not in the Edit block below
    body_at = item.index("const bodyArea = editor.bodyControl(")
    assert body_at < item.index("editor.imagePicker")


def test_the_image_picker_asks_the_server_and_composes_nothing():
    """The list is the server's, and so is the text: images.js sends the item's
    handle and inserts the exact `![alt](src)` line it is handed. Phase 4's
    upload composes the `![alt](…)` wrapper itself (§7 says the client does),
    but the path inside it is still the server's `from_source` -- the client
    never builds a path spelling of its own, the same posture as the link
    picker, and the one that keeps a reference from disagreeing with what the
    build resolves."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "/api/images?item=${encodeURIComponent(handle)}" in picker
    assert "from './api.js'" in picker
    assert "insert(row.markdown)" in picker
    # the upload insertion wraps the server's spelling, nothing of its own
    assert "insert(`![${stemOf(file.name)}](${payload.from_source})`)" in picker
    for invented in ("../",):
        assert invented not in picker, f"the client must not compose {invented!r} itself"


def test_the_upload_ui_is_wired_into_the_image_panel():
    """Phase 4 (§17): drag-and-drop and a file input live in the same panel as
    the Phase 0 list -- the panel editor.js builds and item.js places. A drop
    target and a file input that reach no handler are decoration."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "type = 'file'" in picker
    assert "addEventListener('drop'" in picker
    assert "addEventListener('dragover'" in picker
    assert "event.dataTransfer" in picker
    assert "chooseFile" in picker


def test_the_upload_previews_as_a_data_url_before_any_request():
    """§11 and §17: the author sees the picked bytes -- as a browser-built
    `data:` URL, which the editor CSP (`img-src 'self' data:`) already allows
    -- before a single byte is posted. The POST only happens behind the
    explicit Upload button, so the preview is always the file as picked."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "new FileReader()" in picker
    assert "readAsDataURL" in picker
    assert "previewImg.src = String(reader.result)" in picker
    assert "preview.hidden = false" in picker
    # the request is behind the button, not inside the pick handler
    assert "upload.addEventListener('click', () => sendUpload(''))" in picker


def test_the_upload_posts_raw_bytes_to_the_asset_route():
    """§11: raw bytes as the body, metadata in the query, one dedicated fetch
    in api.js (which owns the launch token). No multipart, no base64 -- both
    explicitly rejected designs (§16.2, §16.3)."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "/api/assets?" in picker
    assert "postRaw" in picker
    assert "FormData" not in picker and "multipart" not in picker
    assert "btoa" not in picker
    with open(os.path.join(STATIC, "api.js"), encoding="utf-8") as fh:
        apijs = fh.read()
    assert "export async function postRaw" in apijs
    assert "'application/octet-stream'" in apijs
    assert "body: bytes" in apijs
    # the token still only ever comes from api.js
    assert "'X-Refdes-Token': token" in apijs
    assert "X-Refdes-Token" not in picker


def test_the_upload_inserts_into_the_draft_and_never_posts_a_body():
    """§7's forced ordering: upload, then insert, then the ordinary Save.
    The upload path must not reach an item-edit endpoint -- the reference
    lands in the draft through the same insert callback the Phase 0 picker
    uses, and default alt text is the filename stem (§7), never empty."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "/api/item/" not in picker
    assert "set_body" not in picker
    assert "stemOf" in picker
    # the insertion is the editor's caret-insert path, shared with Phase 0
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "createImagePicker(item, handle, insertIntoBody)" in editor
    assert "setDraftBody(handle, area.value)" in editor
    assert "area._refdesCommit" in editor


def test_the_binary_conflict_offers_replace_or_cancel():
    """§8's conflict dialog, binary variant: the same visual/interaction
    convention as editor.js's text conflict -- a `.conflict` box, an h3,
    muted facts, a `pre.conflict-diff`, and `.conflict-actions` buttons --
    but with size/hash facts instead of a diff (there is none for two
    binaries), and replace meaning re-issue with the server's `current_hash`
    as `expected_hash`. The disclosure of referencing items (§9.3) is in the
    box, not a second modal (§15.7)."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "el('div', 'conflict')" in picker
    assert "'conflict-diff'" in picker
    assert "'conflict-actions'" in picker
    assert "no visual diff" in picker
    assert "current_hash" in picker and "current_size" in picker
    assert "referenced_by" in picker
    assert "sendUpload(payload.current_hash)" in picker
    assert "'Replace'" in picker and "'Cancel'" in picker
    assert "expected_hash" in picker


def test_a_sealed_refusal_is_a_hard_refusal_not_a_confirmable_conflict():
    """§10: a sealed refusal has no `expected_hash` that unlocks it, so the
    UI must show it as a hard refusal. The replace path is reached only from
    a 409 conflict payload -- exactly one call site passes a server hash --
    and a `kind: refused` payload never renders the conflict box."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "kind === 'refused'" in picker
    assert "refusal === 'sealed'" in picker
    assert "no confirmation unlocks it" in picker
    # the only re-issue with a server-supplied hash is the conflict box's
    # Replace button; the plain upload sends an empty expected_hash
    assert picker.count("sendUpload(payload.current_hash)") == 1
    assert "sendUpload('')" in picker
    # the conflict box is only ever opened from the 409 branch
    assert picker.count("showBinaryConflict(") == 2


def test_the_thumbnail_is_the_preview_surface_and_not_a_new_endpoint():
    """A picker is for choosing a picture, so the row shows one -- from the
    build's own published asset, under the session cookie an `<img>` can carry.
    The CSP forbids an inline onerror, so the fallback for a thumbnail that is
    not in the current generation is a listener, and a failed load leaves the
    row usable."""
    with open(os.path.join(STATIC, "images.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "row.thumb" in picker
    assert "img.src = row.thumb" in picker
    assert "loading = 'lazy'" in picker
    assert "addEventListener('error'" in picker
    assert "onerror" not in picker
    assert "insertable" in picker, "a row the server cannot reference says so"
