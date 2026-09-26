// The image picker: docs/design/editor-image-upload.md §17 Phase 0 -- the v1
// item that never shipped (browser-editor.md, "What v1 must deliver" 5:
// "Existing images by picker; no upload"). It lists the images the project
// already has and inserts a reference to one; it uploads nothing, and the
// server has no write endpoint for it to call.
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

import { api } from './api.js';

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
