// The image picker: docs/design/editor-image-upload.md §17 Phase 0 -- the v1
// item that never shipped (browser-editor.md, "What v1 must deliver" 5:
// "Existing images by picker; no upload"). It lists the images the project
// already has and inserts a reference to one. Phase 4 ("Client") added the
// upload half below the list: drag-and-drop or a file input, a `data:`
// preview of the picked bytes before any request, a raw-bytes POST to
// `/api/assets`, and insertion of the returned `from_source` spelling
// the same draft -- upload never touches a body (§7); the ordinary Save does.
//
// Shape follows links.js: a filter input over a fetched candidate list, a
// button per row, and nothing posted. The inserted text is composed by the
// server -- `_images` sends the exact image line for this item, relative to
// this item's own source file -- and lands in the same draft as a field edit,
// so the one Save, the one revision, and the one conflict screen cover it with
// no special case.
//
// The thumbnail is the preview surface, not a new read endpoint: the row's
// `thumb` is the build's own `assets/...` path, served under the session
// cookie with the preview CSP. An image added since the last rebuild is not in
// that generation yet, so a row that fails to load falls back to its name
// rather than showing a broken-image box.
//
// A row the server marked `insertable: false` keeps its place in the list with
// the server's reason attached and no working button, rather than being hidden:
// the file exists, and "you cannot reference this yet" is a fact the author
// needs more than a shorter list.

import { api, postRaw } from './api.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function humanSize(bytes) {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function stemOf(name) {
  // §7: alt text defaults to the filename stem and is never left empty --
  // `curve.png` gives `![curve](…)`, and a name with no extension is its own
  // stem. The author edits the alt afterwards; the point is it starts whole.
  return name.replace(/\.[^.]+$/, '') || name;
}

function imageNode(row) {
  if (!row.thumb) return null;
  const img = el('img', 'image-thumb');
  img.src = row.thumb;
  img.alt = '';
  img.loading = 'lazy';
  // A row keeps working whether or not the bytes are there: the editor CSP is
  // script-src 'self', so an inline error attribute would do nothing at all and
  // the fallback has to be a listener.
  img.addEventListener('error', () => {
    const placeholder = el('span', 'image-thumb missing', '·');
    if (img.parentNode) img.parentNode.replaceChild(placeholder, img);
  });
  return img;
}

export function createImagePicker(item, handle, insert) {
  const body = (item.edit && item.edit.body) || {};
  const section = el('div', 'images-edit');
  section.appendChild(el('h3', null, 'Images in this project'));
  if (!body.editable) {
    // Same posture as a read-only field: say why rather than offer a button
    // that has nowhere to put anything.
    section.appendChild(el('p', 'muted', body.reason || 'The body of this item is read only.'));
    return section;
  }

  const filter = el('input', 'image-filter');
  filter.type = 'search';
  filter.placeholder = 'filter images…';
  const list = el('div', 'image-list');
  list.appendChild(el('p', 'muted', 'loading images…'));
  section.appendChild(filter);
  section.appendChild(list);

  const note = el('p', 'image-note muted');
  section.appendChild(note);

  // ------------------------------------------------------------- upload
  //
  // Phase 4 (§17): drag-and-drop and a file input, a `data:` preview of the
  // picked bytes BEFORE any request, and insertion of the returned
  // `from_source` spelling into the draft with the stem as default alt text.
  // The upload writes bytes and returns a path; it never touches a body (§7)
  // -- the reference reaches disk through the ordinary Save, the ordinary
  // revision check, and the ordinary delta gate, which is the only ordering
  // the gate admits (§2).
  const drop = el('div', 'image-drop', 'drop an image here, or');
  const pick = el('input', 'image-file');
  pick.type = 'file';
  pick.accept = 'image/png,image/jpeg,image/gif,image/webp';
  section.appendChild(drop);
  section.appendChild(pick);

  const preview = el('div', 'image-upload-preview');
  preview.hidden = true;
  const previewImg = el('img', 'image-preview-img');
  previewImg.alt = '';
  const previewInfo = el('span', 'image-preview-info');
  const upload = el('button', 'btn image-upload', 'Upload');
  const cancelPick = el('button', 'btn image-cancel-pick', 'Cancel');
  preview.appendChild(previewImg);
  preview.appendChild(previewInfo);
  preview.appendChild(upload);
  preview.appendChild(cancelPick);
  section.appendChild(preview);

  // The binary variant of the conflict dialog, in the convention already
  // used by editor.js `showConflict`: a `.conflict` box with an h3,
  // muted facts, a `pre.conflict-diff` block, and `.conflict-actions`
  // buttons. What changes is the content: there is no diff of two PNGs (§8),
  // so the box shows the facts an author can actually compare -- path, size,
  // both hashes, the §9.3 blast radius -- and offers replace or cancel.
  const conflictBox = el('div', 'conflict');
  conflictBox.hidden = true;
  section.appendChild(conflictBox);

  let picked = null;

  function clearPicked() {
    picked = null;
    preview.hidden = true;
    previewImg.removeAttribute('src');
    previewInfo.textContent = '';
    pick.value = '';
    conflictBox.hidden = true;
  }

  function chooseFile(file) {
    if (!file) return;
    picked = file;
    // The preview is built in the browser as a `data:` URL: the editor CSP is
    // `img-src 'self' data:` (§11), so the author sees the exact bytes they
    // are about to upload with no round trip and no new read endpoint. The
    // request happens only when they then press Upload.
    const reader = new FileReader();
    reader.addEventListener('load', () => {
      previewImg.src = String(reader.result);
    });
    reader.readAsDataURL(file);
    previewInfo.textContent = `${file.name} (${humanSize(file.size)})`;
    preview.hidden = false;
    conflictBox.hidden = true;
    upload.disabled = false;
    note.textContent = '';
  }

  function showBinaryConflict(payload) {
    conflictBox.textContent = '';
    conflictBox.hidden = false;
    conflictBox.appendChild(el('h3', null, 'A different file already has that name'));
    conflictBox.appendChild(el('p', 'muted', payload.message || ''));
    const facts = [
      `there: ${payload.path}`,
      `there: ${humanSize(payload.current_size)}, ${payload.current_hash}`,
      `yours: ${picked ? `${picked.name} (${humanSize(picked.size)})` : 'the picked file'}`,
    ];
    const refs = payload.referenced_by || [];
    if (refs.length) {
      facts.push(`replacing it changes what these items show: ${refs.join(', ')}`);
    }
    conflictBox.appendChild(el('pre', 'conflict-diff', facts.join('\n')));
    conflictBox.appendChild(el('p', 'muted',
      'There is no visual diff of two binaries, so these are the facts to compare.'));

    const actions = el('div', 'conflict-actions');
    const replace = el('button', 'btn', 'Replace');
    const cancelConflict = el('button', 'btn', 'Cancel');
    // §8: the re-issue with the hash the server just returned *is* the
    // confirmation (§15.7) -- no second modal, and nothing is sent until the
    // author presses this.
    replace.addEventListener('click', () => sendUpload(payload.current_hash));
    cancelConflict.addEventListener('click', () => {
      conflictBox.hidden = true;
      note.textContent = 'Left the existing file alone.';
      note.className = 'image-note muted';
    });
    actions.appendChild(replace);
    actions.appendChild(cancelConflict);
    conflictBox.appendChild(actions);
  }

  async function sendUpload(expectedHash) {
    const file = picked;
    if (!file) return;
    // §11: metadata in the query, the bytes as the raw body. `item=` defaults
    // the destination to the source directory of this item (§4).
    const params = new URLSearchParams({ item: handle, name: file.name });
    if (expectedHash) params.set('expected_hash', expectedHash);
    upload.disabled = true;
    note.textContent = expectedHash ? 'Replacing…' : 'Uploading…';
    note.className = 'image-note muted';
    try {
      const payload = await postRaw(`/api/assets?${params.toString()}`, file);
      // §7: `from_source` is the exact relative-to-my-source spelling from
      // the server; the client wraps it in an image line and hands it to the
      // same insert callback the Phase 0 picker uses. Nothing is posted here.
      insert(`![${stemOf(file.name)}](${payload.from_source})`);
      conflictBox.hidden = true;
      clearPicked();
      const refs = payload.referenced_by || [];
      const extra = payload.replaced && refs.length
        ? ` It replaced the old file, which these items also show: ${refs.join(', ')}.`
        : '';
      note.textContent = `Uploaded ${payload.rel}. The reference reaches disk when you save.${extra}`;
      note.className = 'image-note good';
    } catch (err) {
      upload.disabled = false;
      const payload = err.payload || {};
      if (err.status === 409 && payload.kind === 'conflict') {
        showBinaryConflict(payload);
        note.textContent = 'The upload stopped: that name already holds different bytes.';
        note.className = 'image-note warn';
        return;
      }
      // A refusal is a hard stop, never a confirmable conflict. The sealed
      // refusals of §10 have no `expected_hash` that unlocks them, so
      // the replace path is only ever reached from a 409 conflict payload.
      if (payload.kind === 'refused') {
        if (payload.refusal === 'sealed') {
          note.textContent = `A seal blocks this upload: ${payload.message || err.message}`
            + ' A sealed entry is append-only, and no confirmation unlocks it.';
        } else {
          note.textContent = `The upload was refused: ${payload.message || err.message}`;
        }
        note.className = 'image-note bad';
        return;
      }
      note.textContent = `The upload failed: ${err.message}`;
      note.className = 'image-note bad';
    }
  }

  upload.addEventListener('click', () => sendUpload(''));
  cancelPick.addEventListener('click', clearPicked);
  pick.addEventListener('change', () => chooseFile(pick.files && pick.files[0]));
  drop.addEventListener('dragover', (event) => {
    event.preventDefault();
    drop.className = 'image-drop over';
  });
  drop.addEventListener('dragleave', () => {
    drop.className = 'image-drop';
  });
  drop.addEventListener('drop', (event) => {
    event.preventDefault();
    drop.className = 'image-drop';
    const files = event.dataTransfer && event.dataTransfer.files;
    chooseFile(files && files[0]);
  });

  function render(all) {
    list.textContent = '';
    const want = filter.value.trim().toLowerCase();
    let shown = 0;
    for (const row of all) {
      if (want && !row.rel.toLowerCase().includes(want)) continue;
      shown += 1;
      const line = el('div', 'image-line');
      const thumb = imageNode(row);
      if (thumb) line.appendChild(thumb);
      const text = el('div', 'image-text');
      text.appendChild(el('span', 'image-name', row.name));
      text.appendChild(el('span', 'image-rel', row.rel));
      text.appendChild(el('span', 'image-size', humanSize(row.bytes)));
      if (row.note) text.appendChild(el('span', 'image-note warn', row.note));
      line.appendChild(text);
      const add = el('button', 'btn image-insert', 'insert');
      add.disabled = !row.insertable;
      add.addEventListener('click', () => {
        // The insertion leaves the caret after the new line in the textarea, so
        // focus stays there: the author keeps typing rather than being sent back
        // to the filter.
        insert(row.markdown);
        note.textContent = `Inserted ${row.name}. It reaches disk when you save.`;
        note.className = 'image-note good';
      });
      line.appendChild(add);
      list.appendChild(line);
    }
    if (!shown) {
      list.appendChild(el('p', 'muted', all.length ? 'no images match' : 'no images to offer'));
    }
  }

  let all = [];
  filter.addEventListener('input', () => render(all));
  api(`/api/images?item=${encodeURIComponent(handle)}`)
    .then((payload) => {
      all = payload.images || [];
      render(all);
      if (!all.length) {
        const dirs = payload.asset_dirs || [];
        note.textContent = dirs.length
          ? `No images under ${dirs.join(', ')}.`
          : 'This project declares no site.assets directories, which is where the picker looks.';
        note.className = 'image-note muted';
      }
    })
    .catch((err) => {
      list.textContent = '';
      list.appendChild(el('p', 'banner bad', `images failed: ${err.message}`));
    });

  return section;
}
