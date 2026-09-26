**An image picker in the browser editor** (Phase 0 of
`docs/design/editor-image-upload.md`). Open an item, and the body control now
carries a picker: it lists every image under your declared `site.assets:`
directories — the same set the build searches, so a reference the picker offers
is a reference a build resolves — with a thumbnail, the file's name and path,
and its size. Pick one and the line to insert is composed for you, relative to
that item's own source file, with the alt text defaulted to the filename's
stem; the text lands in the draft and reaches disk on the ordinary Save, with
the usual revision check, delta gate, and conflict screen. Nothing is uploaded
and no new write endpoint exists: the picker can only reference images the
project already has, and a filename markdown would percent-encode (one with a
space in it, say) is listed but marked as not referenceable rather than handed
over as text the save would refuse. Thumbnails come from the rendered preview
the server already serves, under the same session cookie as every other preview
page, so there is no new file-read surface.

`GET /api/images?item=<ref>` is the list itself, and a `--no-write` server
answers it like any other read.
