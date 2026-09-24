// The New Item form: docs/design/browser-editor.md, Slice 3 -- creation.
// The id shown here is what the server's pure planner says WOULD be minted,
// refreshed as the type, board, or explicit override change -- nothing is
// reserved until Create is pressed, and the service re-plans under the save
// lock, so a preview can never burn a number. The destination arrives as a
// suggestion and stays a plain editable path (suggest plus override). Field
// controls are the same ones editor.js uses (controls.js); the schema comes
// from /api/create/schema, so nothing here re-implements a project fact --
// and the client never mints a key or writes a DISPLAY-ID@key composite.

import { api } from './api.js';
import { fieldControlNode } from './controls.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function row(label, node) {
  const wrap = el('div', 'create-row');
  wrap.appendChild(el('label', null, label));
  wrap.appendChild(node);
  return wrap;
}

export function createForm(initial = {}) {
  const block = el('section', 'detail-block create-block');
  block.appendChild(el('h2', null, 'New item'));
  block.appendChild(el('p', 'muted', 'Loading the schema…'));

  api('/api/create/schema')
    .then(build)
    .catch((err) => {
      block.textContent = '';
      block.appendChild(el('p', 'banner bad', `Could not load the create schema: ${err.message}`));
    });
  return block;

  function build(schema) {
    block.textContent = '';
    const byName = {};
    for (const one of schema.types) byName[one.name] = one;

    const messages = el('div', 'edit-messages');
    block.appendChild(messages);

    if (initial.amends) {
      block.appendChild(el(
        'p',
        'amends-note',
        `This entry amends ${initial.amends}. A sealed entry is never edited — the correction is this new entry, and the sealed one keeps its bytes.`,
      ));
    }

    const typeSelect = el('select', 'create-type');
    for (const one of schema.types) {
      const option = el('option', null, `${one.label || one.name} (${one.prefix})`);
      option.value = one.name;
      typeSelect.appendChild(option);
    }
    if (initial.type && byName[initial.type]) typeSelect.value = initial.type;

    let boardSelect = null;
    if ((schema.boards || []).length) {
      boardSelect = el('select', 'create-board');
      boardSelect.appendChild(el('option', null, '(file default)'));
      for (const board of schema.boards) boardSelect.appendChild(el('option', null, board));
      if (initial.board) boardSelect.value = initial.board;
    }

    const idInput = el('input', 'create-id');
    idInput.placeholder = 'next free';
    const idPreview = el('span', 'badge id-preview');

    const destInput = el('input', 'create-destination');
    let destDirty = false;
    destInput.addEventListener('input', () => {
      destDirty = true;
      refreshPreview();
    });

    const fieldsBox = el('div', 'create-fields');

    const create = el('button', 'btn create-save', 'Create');

    if (boardSelect) block.appendChild(row('Board', boardSelect));
    block.appendChild(row('Type', typeSelect));
    const idRow = row('ID', idInput);
    idRow.appendChild(idPreview);
    block.appendChild(idRow);
    block.appendChild(row('Destination', destInput));
    block.appendChild(fieldsBox);
    block.appendChild(create);

    function currentSpec() {
      return byName[typeSelect.value];
    }

    function renderFields() {
      fieldsBox.textContent = '';
      const spec = currentSpec();
      if (!spec) return;
      for (const [name, fspec] of Object.entries(spec.fields)) {
        if (!fspec.creatable) continue;
        const controlSpec =
          fspec.type === 'enum' && fspec.choices
            ? { control: 'select', choices: fspec.choices }
            : { control: 'text' };
        const control = fieldControlNode(controlSpec, fspec.default ?? '', () => {});
        control.dataset.field = name;
        fieldsBox.appendChild(row(fspec.required ? `${name} *` : name, control));
      }
    }

    async function refreshPreview() {
      const params = new URLSearchParams({ type: typeSelect.value });
      if (boardSelect && boardSelect.value) params.set('board', boardSelect.value);
      if (idInput.value.trim()) params.set('id', idInput.value.trim());
      try {
        const prev = await api(`/api/create/preview?${params.toString()}`);
        if (prev.id) {
          idPreview.textContent = `would be ${prev.id}`;
          idPreview.className = 'badge id-preview';
        } else {
          idPreview.textContent = prev.reason || 'no id';
          idPreview.className = 'badge bad';
        }
        if (!destDirty && prev.destination) {
          destInput.value = prev.destination;
          destInput.placeholder = prev.destination;
        }
      } catch (err) {
        idPreview.textContent = `preview failed: ${err.message}`;
        idPreview.className = 'badge bad';
      }
    }

    typeSelect.addEventListener('change', () => {
      renderFields();
      refreshPreview();
    });
    if (boardSelect) boardSelect.addEventListener('change', refreshPreview);
    idInput.addEventListener('input', refreshPreview);

    create.addEventListener('click', async () => {
      const fields = {};
      for (const control of fieldsBox.querySelectorAll('[data-field]')) {
        if (control.value === '') continue; // a missing required field is the gate's to report
        fields[control.dataset.field] = control.value;
      }
      if (boardSelect && boardSelect.value) fields.board = boardSelect.value;
      const body = { type: typeSelect.value, fields };
      if (idInput.value.trim()) body.id = idInput.value.trim();
      if (destInput.value.trim()) body.destination = destInput.value.trim();
      if (initial.amends) body.amends = initial.amends;

      create.disabled = true;
      messages.textContent = 'Creating…';
      messages.className = 'edit-messages muted';
      try {
        const made = await api('/api/items/create', { method: 'POST', body });
        messages.textContent = `Created ${made.id} in ${made.path}.`;
        messages.className = 'edit-messages good';
        location.hash = `#/items/${encodeURIComponent(made.id)}`;
      } catch (err) {
        create.disabled = false;
        const payload = err.payload || {};
        messages.textContent = payload.reason || payload.error || err.message;
        messages.className = 'edit-messages bad';
      }
    });

    renderFields();
    refreshPreview();
  }
}
