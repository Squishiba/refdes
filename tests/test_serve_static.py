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


def strip_js_comments(text):
    """Blank out `//` and `/* */` comments, string-aware. The regex scans in
    this file are naive (no parser), so prose in a comment -- a possessive
    apostrophe, the word "evaluate", an `on...` mention -- used to trip them,
    which bent production comments into awkward phrasings. Scan code, not
    prose: strip the comments first, then assert on what the engine runs.
    Backtick templates are treated as plain strings (house style, naive)."""
    out = []
    i = 0
    n = len(text)
    in_string = None
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "'\"`":
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def js_code(name):
    """A served module's code with comments stripped: the surface the
    behavioral pins in this file assert against (see strip_js_comments)."""
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return strip_js_comments(fh.read())


@pytest.mark.parametrize("name", js_files())
def test_no_inline_handlers_or_dynamic_code_in_served_js(name):
    text = js_code(name)
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
        text = js_code(name)
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


def test_markdown_docs_describe_the_shipped_image_upload_contract():
    """Keep the author-facing upload section aligned with the implemented
    format/size limits and upload-then-save flow."""
    docs = os.path.join(os.path.dirname(STATIC), "..", "..", "..", "docs")
    with open(os.path.join(docs, "markdown.md"), encoding="utf-8") as fh:
        markdown = fh.read()
    section = markdown.split("### Uploading an image from the browser editor", 1)[1]
    section = section.split("### Width and captions", 1)[0]
    for claim in (
        "PNG, JPEG, GIF, or WebP",
        "8 MiB",
        "does not edit the item's Markdown",
        "ordinary **Save**",
        "sealed entry",
    ):
        assert claim in section

    with open(os.path.join(docs, "design", "browser-editor.md"), encoding="utf-8") as fh:
        design = fh.read()
    deferred = design.split("### Deferred", 1)[1].split("### ", 1)[0]
    later = design.split("### Later", 1)[1].split("### ", 1)[0]
    assert "Image upload has shipped" in deferred
    assert "Image management beyond upload" in later


# ------------------------------------------------------------ source picker


def test_the_picker_is_wired_into_the_editor():
    """The new module must be imported, placed under the body control, and
    send pins with the existing body save. The import-graph test checks that
    the module itself resolves."""
    assert os.path.isfile(os.path.join(STATIC, "sourcepicker.js"))
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "from './sourcepicker.js'" in editor
    assert "createSourcePicker(item, handle, edit.body && edit.body.editable ? acceptSource : null)" in editor
    assert "editor.sourcePicker" in item
    assert item.index("const bodyArea = editor.bodyControl(") < item.index("editor.sourcePicker")
    assert "{ pin: draft.pins }" in editor
    assert "op: 'set_body'" in editor


def test_the_browser_parses_no_csv():
    """The picker sees only JSON from the three service reads. It never
    fetches a source path or splits file text into rows or cells."""
    with open(os.path.join(STATIC, "sourcepicker.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "from './api.js'" in picker
    assert "api(base)" in picker
    assert "${base}/entries?" in picker
    assert "${base}/propose?" in picker
    assert "payload.entries" in picker and "initial.entry" in picker
    assert ".split(',')" not in picker and '.split(",")' not in picker
    assert ".split('\\n')" not in picker and '.split("\\n")' not in picker
    assert "fetch(" not in picker and "FileReader" not in picker
    assert "source(\"" not in picker, "the server composes the calc line"


def test_the_picker_inserts_through_the_existing_draft_mechanism():
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    with open(os.path.join(STATIC, "drafts.js"), encoding="utf-8") as fh:
        drafts = fh.read()
    with open(os.path.join(STATIC, "sourcepicker.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "setDraftBody(handle, area.value)" in editor
    assert "addDraftPin(handle" in editor
    assert "pin: draft.pins" in editor
    assert "return saveAll()" in editor
    assert "method: 'POST'" in editor and "op: 'set_body'" in editor
    assert "pins: parsed.pins || []" in drafts
    assert "proposal.line" in editor
    assert "insertIntoBody(proposal.line)" not in editor
    assert "if (!blocks.length) throw new Error" in editor
    assert "blocks[blocks.length - 1]" in editor
    assert "body.indexOf('\\n', caret)" in editor
    for name in ("accept_source", "pin_source", "source_accept"):
        assert f"op: '{name}'" not in editor + picker


def test_the_unit_field_starts_empty_and_accept_is_disabled_until_it_is_filled():
    with open(os.path.join(STATIC, "sourcepicker.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "unit.value = ''" in picker
    assert "button.disabled = true" in picker
    assert "if (!chosenUnit || !chosenName" in picker
    assert "button.disabled = !accept || !current || !unit.value.trim()" in picker
    assert "initial.units" in picker and "unit.value = value" in picker
    assert "line.textContent = proposal.line" in picker


# --------------------------------------------------------- PDF picker (P-B)


def source_picker_text():
    with open(os.path.join(STATIC, "sourcepicker.js"), encoding="utf-8") as fh:
        return fh.read()


def test_the_pdf_page_view_parses_no_pdf_in_the_browser():
    picker = source_picker_text()
    assert "${base}/page?path=" in picker
    assert "payload.spans" in picker and "payload.page_box" in picker
    assert "span.x - left" in picker and "top - span.y" in picker
    assert "span.size" in picker
    assert "Positioned-text reconstruction" in picker
    assert "no graphics or original fonts" in picker
    for forbidden in ("pdf.js", "pdfjs", "FileReader", "arrayBuffer", "fetch(", "innerHTML"):
        assert forbidden not in picker
    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert ".source-page-span { position: absolute" in css
    assert ".source-page-viewport" in css and "overflow: auto" in css


def test_the_pdf_confirm_step_reuses_the_csv_confirm_panel_and_its_empty_unit_field():
    picker = source_picker_text()
    assert "file.browse === 'rows' || file.browse === 'pages'" in picker
    assert "function showConfirm(path, key, pdf = null)" in picker
    assert picker.count("'Confirm source value'") == 1
    assert picker.count("const unit = el('input', 'source-unit')") == 1
    assert "unit.value = ''" in picker and "unit.placeholder" not in picker
    assert "candidateList(pdf.payload, entry.row)" in picker
    for text in ("Whole row", "Quoted row to record", "Column header guess", "Source key"):
        assert text in picker
    assert "token.index === entry.token ? 'mark' : 'span'" in picker
    assert "pinned.querySelector('.source-value').textContent = proposal.entry.pinned" in picker


def test_nothing_is_preselected_even_when_the_page_has_exactly_one_candidate():
    picker = source_picker_text()
    listing = picker[picker.index("function candidateList"):picker.index("function highlightPdf")]
    assert "row.tokens.filter((token) => token.candidate)" in listing
    assert "column header guess:" in listing
    assert "addEventListener('click', () => showConfirm" in listing
    page = picker[picker.index("function showPage"):picker.index("files.appendChild(el('p'")]
    assert "showConfirm(" not in page
    assert "candidate_count === 1" not in picker
    assert ".click()" not in picker and ".selected =" not in picker


def test_pdf_navigation_and_failures_clear_stale_picks_and_report_the_server_reason():
    picker = source_picker_text()
    page = picker[picker.index("function showPage"):picker.index("files.appendChild(el('p'")]
    assert "const request = ++rowRequest" in page
    assert "proposalRequest += 1" in page and "confirm.textContent = ''" in page
    assert "if (request !== rowRequest) return" in page
    assert "showPage(file.path)" in picker  # initial read omits page
    for text in ("payload.prev", "payload.next", "payload.cited.detail", "payload.detail",
                 "payload.too_dense", "payload.drifted", "err.message", "Retry page"):
        assert text in page
    assert "if (payload.too_dense) return" in page
    assert "highlightPdf(pdf.payload, pdf.row, pdf.token)" in picker
    assert "source-page-row-highlight" in picker and "source-page-token-highlight" in picker


def test_pdf_confirm_uses_the_existing_save_path_and_persists_its_session_selection():
    picker = source_picker_text()
    assert "current.accept_supported === false || busy" in picker
    assert "proposal.accept_supported === false || busy" in picker
    assert "initial.accept_reason" in picker
    assert "sha256=${encodeURIComponent(pdf.payload.sha256)}" in picker
    assert "const saved = await accept(current)" in picker
    assert "method: 'POST'" not in picker and "op:" not in picker
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "...(proposal.reader === 'pdf' ? {" in editor
    assert "page: proposal.page, row: proposal.row, token: proposal.token" in editor
    assert "sha256: proposal.sha256" in editor
    assert "setDraftBody(handle, area.value)" in editor
    assert "addDraftPin(handle, {" in editor
    assert "quoted: proposal" not in editor and "value: proposal.entry" not in editor


# ------------------------------------------------------------ live inline calc (slice B)


def test_the_live_calc_panel_is_wired_into_the_body():
    """Slice B's panel has to reach the page the same way every earlier panel
    did: the module exists, editor.js imports and attaches it to the body
    textarea, item.js places it under that textarea beside the pickers, and a
    teardown sweep destroys it before the container it lives in is cleared."""
    assert os.path.isfile(os.path.join(STATIC, "live-calc.js"))
    editor = js_code("editor.js")
    item = js_code("item.js")
    assert "from './live-calc.js'" in editor
    assert "createLiveCalc(handle, {" in editor
    assert "liveCalc.attach(area)" in editor
    assert "liveCalcPanel: liveCalc.node" in editor
    assert "editor.liveCalcPanel" in item
    # under the textarea, beside the pickers (the image/source placement rule)
    body_at = item.index("const bodyArea = editor.bodyControl(")
    assert body_at < item.index("editor.liveCalcPanel")
    assert body_at < item.index("editor.imagePicker")
    # and destroyed with the view it lives in, not left listening: EVERY
    # path that clears the container destroys the panel first -- the helper
    # is defined before the first clear, and there is a destroy call for
    # every clear (item switch, fetch error, normal swap).
    assert item.index("destroyLiveCalc(container)") < item.index("container.textContent = ''")
    assert item.count("destroyLiveCalc(container);") == item.count("container.textContent = '';")
    assert "querySelectorAll('.live-calc')" in item
    assert "_refdesLiveCalc.destroy()" in item
    assert item.index("_refdesLiveCalc.destroy()") < item.index("restoreFocus(container, focus)")
    # the shell's own clears of the same pane (create form, empty selection)
    # tear the panel down too -- the helper is exported for exactly this
    assert "export function destroyLiveCalc" in item
    app = js_code("app.js")
    assert "renderItem, destroyLiveCalc } from './item.js'" in app
    assert app.count("destroyLiveCalc(detailPane)") == 2  # create form, empty selection
    # the controller is built only for an editable form (after the early
    # return), and both return shapes carry the same keys
    assert editor.index("if (!edit.editable)") < editor.index("const liveCalc = createLiveCalc")
    assert editor.count("liveCalcPanel: null") == 1


def test_the_panel_reads_the_forms_own_revision_and_the_save_window():
    """The §3.6 guards read the editor's own state through accessors -- the
    form's live `revision` variable (the same string saveAll sends as
    expected_revision) and a flag set for the whole save round-trip. A panel
    with a stale copy of either would discard live responses or stomp a save."""
    editor = js_code("editor.js")
    assert "getRevision: () => revision" in editor
    assert "isSaving: () => saving" in editor
    assert "getFields: () => draft.fields" in editor
    assert editor.index("let saving = false") < editor.index("const liveCalc = createLiveCalc")
    assert "saving = true" in editor
    # the flag drops in `finally`: a failed save must not silence the panel
    assert "saving = false" in editor and "} finally {" in editor
    assert editor.index("} finally {") < editor.index("\n      saving = false;")
    panel = js_code("live-calc.js")
    assert "export function createLiveCalc" in panel
    # the guard is the editor's revision, never app.js's openRevision
    assert "openRevision" not in panel
    assert "payload.revision !== getRevision()" in panel
    # the second guard: the textarea's text as of the REQUEST (the response
    # path: typing during the network beat discards the response silently)
    assert "area.value !== sent" in panel
    # ... and as of the visible rows (the apply path: Fill is inert against
    # a snapshot it no longer describes)
    assert "area.value !== snapshotText" in panel


def test_the_calc_request_is_debounced_carries_the_bag_and_is_abortable():
    """§3.1/§3.3: a 400 ms trailing debounce, the request body is
    `{text, fields}` with the draft's live bag, and each request owns an
    AbortController signal threaded through api.js (guard 1: the in-flight
    request of superseded text is aborted, not awaited)."""
    panel = js_code("live-calc.js")
    assert "const DEBOUNCE_MS = 400" in panel
    assert "setTimeout(" in panel and "clearTimeout(" in panel
    assert "/calc`," in panel
    assert "body: { text, fields: getFields() }" in panel
    assert "new AbortController()" in panel
    assert "signal: controller.signal" in panel
    apijs = js_code("api.js")
    assert "{ method = 'GET', body, signal } = {}" in apijs
    assert "init.signal = signal" in apijs


def test_the_auto_fill_toggles_on_one_persisted_preference():
    """§3.5/§6.1: one localStorage key, default ON (absence is on), and the
    gate reads `stale` -- never `computed !== stored`, the D1 rule an
    ok-within-window literal (`4.4 V` vs computed `4.436 V`) survives."""
    panel = js_code("live-calc.js")
    assert "refdes.live-calc.autofill" in panel
    assert "!== 'off'" in panel  # default on: only an explicit 'off' turns it off
    assert "status === 'stale'" in panel
    # auto-fill's gate is the same gate, phrased as a skip (the Fill-button
    # check alone would let a scheduled auto-fill mutate a non-stale row)
    assert "span.status !== 'stale'" in panel
    # the pair is enforced, not just one boundary: a span missing its
    # result_end is display-only everywhere (Fill button, auto-fill gate,
    # and the offset conversion itself, which has no half-pair path)
    assert panel.count("span.result_end !== undefined") == 1
    assert panel.count("span.result_end === undefined") == 2
    # the Case B stand-down is SESSION-scoped (a browser session outlives
    # every controller: the flag lives in sessionStorage, not in the closure)
    assert "refdes.live-calc.fallback" in panel
    assert "sessionStorage.getItem(FALLBACK_KEY)" in panel
    assert "let sessionFallback = readFallbackFlag();" in panel
    assert "writeFallbackFlag();" in panel
    # it says so, in a line that survives the controller rebuild
    assert "auto-fill is off for this session (undo is unavailable here); Fill still works" in panel
    assert "sessionOff.hidden = !sessionFallback;" in panel
    # the checkbox shows the EFFECTIVE state, never a lying ON
    assert "readAutofillPref() && !sessionFallback" in panel
    # the author's live selection (non-collapsed) blocks fills it overlaps
    assert "const e = area.selectionEnd" in panel
    assert "s < off.resultEnd && e > off.resultStart" in panel
    # the offset conversion computes the line starts ONCE per batch
    assert "function toOffsets" not in panel
    assert panel.count("lineStarts(") == 3  # definition + one call per apply path
    assert "const starts = lineStarts(text);" in panel
    # the truncation footer mirrors the server's limit, not a magic number
    js_limit = re.search(r"const PREVIEW_SPAN_LIMIT = (\d+)", panel)
    assert js_limit is not None, "the panel must name the span limit as a constant"
    build_py = os.path.join(os.path.dirname(os.path.dirname(STATIC)), "build.py")
    with open(build_py, encoding="utf-8") as fh:
        py = fh.read()
    py_limit = re.search(r"PREVIEW_SPAN_LIMIT = (\d+)", py)
    assert py_limit is not None and js_limit.group(1) == py_limit.group(1), (
        "the panel's truncation footer no longer mirrors build.PREVIEW_SPAN_LIMIT"
    )
    assert "showing the first ${PREVIEW_SPAN_LIMIT} spans" in panel
    # fills go through the native undo path first (Case A), splice as Case B
    assert "execCommand('insertText'" in panel
    # a Case B splice fires no input event: the apply path schedules the
    # recalculation the browser commit cannot
    assert "if (spliced) schedule();" in panel
    # the panel writes text through exactly one path (the Case B splice;
    # Case A goes through execCommand, which mutates natively)
    assert panel.count("area.value = ") == 1
    assert "innerHTML" not in panel


# ------------------------------------------------------------ formatting bar (slice 1)


def test_the_format_bar_is_wired_into_the_body():
    """The bar has to reach the page the same way the pickers and the live-calc
    panel do: the module exists, editor.js imports and attaches it to the body
    textarea, and item.js mounts it immediately above that textarea."""
    assert os.path.isfile(os.path.join(STATIC, "formatbar.js"))
    editor = js_code("editor.js")
    item = js_code("item.js")
    assert "from './formatbar.js'" in editor
    assert "createFormatBar(handle, { isSaving: () => saving })" in editor
    assert "area._refdesFormatBar = formatBar.node;" in editor
    assert "formatBar.attach(area);" in editor
    assert editor.index("if (!edit.editable)") < editor.index("const formatBar = createFormatBar")
    assert editor.count("area._refdesFormatBar = formatBar.node;") == 1
    assert editor.count("formatBar.attach(area);") == 1

    assert "body.appendChild(bodyArea._refdesFormatBar);" in item
    assert item.index("body.appendChild(bodyArea._refdesFormatBar);") < item.index(
        "body.appendChild(bodyArea);"
    )

    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert ".format-bar" in css
    assert ".fmt-core" in css
    assert ".fmt-btn" in css
    assert ".format-bar-note" in css


def test_the_format_bar_shares_the_case_a_b_mutator_and_save_gate():
    """The bar must mutate through one shared path, not by writing to the
    textarea ad hoc: Case A tries the native insertion once, Case B splices and
    dispatches exactly one synthetic input event. The same save-window gate as
    live-calc must stop both the bar and the editor's insertion helpers."""
    bar = js_code("formatbar.js")
    editor = js_code("editor.js")

    assert "export function applyEdit(" in bar
    assert "export function blockInsertPlan(" in bar
    assert "export function createFormatBar(" in bar
    assert "export const SHORTCUTS = [" in bar
    assert bar.count("document.execCommand('insertText', false, text)") == 1
    assert bar.count("area.value = ") == 1
    assert bar.count("area.dispatchEvent(new Event('input', { bubbles: true }))") == 1
    assert "if (opts.isSaving && opts.isSaving()) return false;" in bar
    assert "const FALLBACK_KEY = 'refdes.live-calc.fallback'" in bar
    assert "Undo may need more than one step in this browser." in bar
    assert "note.hidden = !readFallbackFlag();" in bar
    assert "if (opts.fallback) opts.fallback();" in bar
    assert "innerHTML" not in bar

    assert "const plan = blockInsertPlan(area, text);" in editor
    assert "plan.caret," in editor
    assert "if (!applyEdit(area, at, at, inserted, after, after, { isSaving: () => saving })) return;" in editor


def test_the_format_bar_is_real_buttons_and_only_the_bounded_shortcuts():
    """§B: real focusable buttons, labels, no focus stealing, and only the
    shortcuts whose browser-reserved neighbors were explicitly checked."""
    bar = js_code("formatbar.js")
    ops_source = _section(bar, "const OPS = {")
    for op in ("bold", "italic", "strike", "code", "heading", "list", "numbered",
               "quote", "link", "table", "hr"):
        assert re.search(rf"^  {op}:", ops_source, re.MULTILINE), op
        assert f"['{op}'," in bar, op
    assert "button.type = 'button';" in bar
    assert "button.setAttribute('aria-label', aria);" in bar
    assert "addEventListener('mousedown', (event) => event.preventDefault());" in bar
    assert "addEventListener('click', () => run(op));" in bar
    assert "if (!area || (isSaving && isSaving())) return;" in bar
    assert bar.count("if (isSaving && isSaving()) return;") == 1
    assert "(event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey" in bar
    assert "String(event.code) === 'Digit5'" in bar
    assert "event.preventDefault();" in bar
    assert bar.count("event.preventDefault()") == 2


def _section(source, marker):
    start = source.index(marker)
    end = source.index("\n};", start)
    return source[start:end]


def test_the_format_bar_binds_exactly_the_collision_audited_shortcuts():
    """§B binds exactly five shortcuts and the exact set is the audited one.
    The never-bound list (Ctrl+S, Ctrl+Z/Y/Shift+Z, Ctrl+Shift+I/J/C, F12,
    Ctrl+T/N/W/L/J/Tab, Ctrl+1..9, Ctrl+Alt+letter, Ctrl+Alt+digit) must be
    absent from SHORTCUTS; a sixth colliding shortcut fails here."""
    bar = js_code("formatbar.js")
    start = bar.index("export const SHORTCUTS = [")
    end = bar.index("\n];", start)
    shortcuts = bar[start:end]

    blocks = re.split(r"\n\s*\{\n", shortcuts)[1:]
    assert len(blocks) == 5, blocks

    expected_ops = {"bold", "italic", "link", "strike", "code"}
    seen = {}
    for block in blocks:
        op_match = re.search(r"op: '([a-z]+)'", block)
        assert op_match is not None, block
        op = op_match.group(1)
        keys = set(re.findall(r"toLowerCase\(\) === '([a-z0-9]+)'", block))
        codes = set(re.findall(r"String\(event\.code\) === '([^']+)'", block))
        ctrlmeta = "event.ctrlKey || event.metaKey" in block
        alt = re.search(r"(?<!!)event\.altKey", block) is not None
        shift = re.search(r"(?<!!)event\.shiftKey", block) is not None
        seen[op] = (keys, codes, ctrlmeta, alt, shift)

    assert set(seen) == expected_ops, seen

    never_bound_keys = {
        "s", "z", "y", "t", "n", "w", "l", "j", "tab", "f12",
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    }
    assert not ({k for v in seen.values() for k in v[0]} & never_bound_keys), seen
    assert not ({c for v in seen.values() for c in v[1]} - {"Digit5"}), seen
    assert not {op: v for op, v in seen.items() if v[3] and v[4]
                and op not in {"strike"}}, "only Alt+Shift+5 binds a shift-key shortcut"

    assert seen["bold"] == ({"b"}, set(), True, False, False)
    assert seen["italic"] == ({"i"}, set(), True, False, False)
    assert seen["link"] == ({"k"}, set(), True, False, False)
    assert seen["strike"] == (set(), {"Digit5"}, False, True, True)
    assert seen["code"] == ({"c"}, set(), True, True, False)


def test_the_font_setting_is_wired_into_the_editor():
    assert os.path.isfile(os.path.join(STATIC, "fontsetting.js"))

    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './fontsetting.js'" in editor
    assert "createFontSetting()" in editor
    assert "fontSetting.applyTo(area)" in editor
    assert "fontBar: fontSetting.node" in editor

    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "if (editor.fontBar) body.appendChild(editor.fontBar);" in item

    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert "var(--refdes-editor-font, monospace)" in css
    assert "var(--refdes-editor-size, 12px)" in css
    assert "var(--refdes-editor-line-height, 1.5)" in css
