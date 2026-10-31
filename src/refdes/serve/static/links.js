// Link pickers: docs/design/browser-editor.md, "Slice 2 -- structured links".
// One picker per verb the server declared editable (`item.edit.links`), with
// the schema-declared target types of the verb deciding which items the
// picker offers -- fetched through the same /api/items filter the list pane
// uses, so there is one query language and one snapshot behind both (an
// empty declared list means the verb accepts any type, so the picker
// fetches the unfiltered list). Adds and removes are draft ops like a
// field edit: nothing posts until Save, and the same revision check,
// conflict screen, and refusal handling cover them.
//
// The picker never sends a composite: it sends the handle of the candidate
// and the service writes DISPLAY-ID@key. Removal names the target as it is
// written on the item, and the service matches it by display or key half.

import { getDraft, draftLinkAdd, draftLinkRemove, draftLinkCancel } from './drafts.js';
import { displayHalf, candidatesFor, rowLabel, matchesFilter } from './pickers.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function verbPicker(item, handle, verb, spec, onChange) {
  const wrap = el('div', 'link-verb-edit');
  const draft = getDraft(handle);
  const serverTargets = spec.targets || [];

  const head = el('h4', null, verb);
  wrap.appendChild(head);
  if (!spec.editable) {
    wrap.appendChild(el('p', 'muted', spec.reason || 'not editable'));
    return wrap;
  }

  const current = el('div', 'link-current');
  wrap.appendChild(current);

  // What the item will link after the draft applies: the targets on the
  // server minus pending removes plus pending adds.
  function effective() {
    const removed = new Set(draft.links.remove[verb] || []);
    const kept = serverTargets.filter((t) => !removed.has(t));
    const added = draft.links.add[verb] || [];
    return { kept, added, removed: [...removed] };
  }

  function isLinked(row) {
    const { kept, added } = effective();
    const all = kept.concat(added);
    const id = row.id || row.handle;
    return all.some(
      (t) => displayHalf(t) === id || (row.key && t.slice(t.lastIndexOf('@') + 1) === row.key)
    );
  }

  // The server text of the link for a candidate row, when the item links it
  // on the server: adding such a row back can only cancel a pending remove,
  // never mint an add of a link that already exists.
  function serverTargetFor(row) {
    const id = row.id || row.handle;
    return serverTargets.find(
      (t) => displayHalf(t) === id || (row.key && t.slice(t.lastIndexOf('@') + 1) === row.key)
    );
  }

  // The picker never offers the item being edited: self-links make no
  // sense to pick from a list, the build cycle checks refuse the directed
  // self-cycles of the standard at save time, and verbs without a cycle
  // rule would accept one silently.
  function isSelf(row) {
    if (row.handle && row.handle === handle) return true;
    if (row.key && item.key && row.key === item.key) return true;
    return Boolean(item.id && row.id === item.id);
  }

  function refresh() {
    current.textContent = '';
    const { kept, added, removed } = effective();
    if (!kept.length && !added.length && !removed.length) {
      current.appendChild(el('span', 'muted', 'no links'));
    }
    for (const target of kept) {
      const line = el('div', 'link-line');
      line.appendChild(el('span', 'link-target', displayHalf(target)));
      const off = el('button', 'btn link-remove', 'remove');
      off.addEventListener('click', () => {
        draftLinkRemove(handle, verb, target);
        refresh();
        onChange();
      });
      line.appendChild(off);
      current.appendChild(line);
    }
    for (const target of added) {
      const line = el('div', 'link-line pending add');
      line.appendChild(el('span', 'link-target', displayHalf(target)));
      line.appendChild(el('span', 'badge', 'will add'));
      const undo = el('button', 'btn link-undo', 'undo');
      undo.addEventListener('click', () => {
        draftLinkCancel(handle, verb, target); // cancels the pending add
        refresh();
        onChange();
      });
      line.appendChild(undo);
      current.appendChild(line);
    }
    for (const target of removed) {
      const line = el('div', 'link-line pending remove');
      line.appendChild(el('span', 'link-target', displayHalf(target)));
      line.appendChild(el('span', 'badge bad', 'will remove'));
      const undo = el('button', 'btn link-undo', 'undo');
      undo.addEventListener('click', () => {
        draftLinkCancel(handle, verb, target); // cancels the pending remove
        refresh();
        onChange();
      });
      line.appendChild(undo);
      current.appendChild(line);
    }
    for (const button of pickers.querySelectorAll('button.link-add')) {
      const row = rows.get(button.dataset.row);
      button.disabled = row && isLinked(row);
    }
  }

  // -- candidate side: the filtered list API, scoped to the declared types.
  const filter = el('input', 'link-filter');
  filter.type = 'search';
  filter.placeholder = `filter ${verb} targets…`;
  const pickers = el('div', 'link-candidates');
  pickers.appendChild(el('p', 'muted', 'loading candidates…'));
  wrap.appendChild(filter);
  wrap.appendChild(pickers);

  const rows = new Map(); // row id -> candidate row, for isLinked lookups
  let totalFound = null; // full count of the list, when it exceeds the page

  function renderCandidates(all) {
    pickers.textContent = '';
    const want = filter.value.trim().toLowerCase();
    let shown = 0;
    for (const row of all) {
      if (isSelf(row)) continue;
      const label = rowLabel(row);
      if (want && !matchesFilter(row, want)) continue;
      shown += 1;
      const line = el('div', 'link-line candidate');
      line.appendChild(el('span', 'link-target', label));
      const add = el('button', 'btn link-add', 'add');
      add.dataset.row = String(shown);
      rows.set(String(shown), row);
      add.addEventListener('click', () => {
        // The add button is enabled for a server link precisely when it is
        // pending-removed, so for a server row "add" cancels that removal
        // (under the stored target text); only a non-server row is a new add.
        const server = serverTargetFor(row);
        if (server) draftLinkCancel(handle, verb, server);
        else draftLinkAdd(handle, verb, row.handle || row.id);
        refresh();
        onChange();
      });
      line.appendChild(add);
      pickers.appendChild(line);
    }
    if (!shown) pickers.appendChild(el('p', 'muted', 'no candidates match'));
    // Count what is pickable, not what was fetched: the self row (at most
    // one, the item under edit) is in the fetched page and in the server
    // total, and is offered by neither -- the counts must not claim it.
    const selfRows = all.filter(isSelf).length;
    const offered = all.length - selfRows;
    const pickable = totalFound === null ? null : totalFound - selfRows;
    if (pickable !== null && offered < pickable)
      pickers.appendChild(el('p', 'muted', `showing the first ${offered} of ${pickable} targets -- the filter searches only these`));
  }

  let all = [];
  filter.addEventListener('input', () => renderCandidates(all));
  candidatesFor(spec.target_types)
    .then((found) => {
      all = found.items;
      totalFound = found.total;
      renderCandidates(all);
      refresh();
    })
    .catch((err) => {
      pickers.textContent = '';
      pickers.appendChild(el('p', 'banner bad', `candidates failed: ${err.message}`));
    });

  refresh();
  return wrap;
}

export function createLinksSection(item, handle, onChange) {
  const verbs = Object.entries((item.edit && item.edit.links) || {});
  if (!verbs.length) return null;
  const section = el('div', 'links-edit');
  section.appendChild(el('h3', null, 'Links'));
  for (const [verb, spec] of verbs) {
    section.appendChild(verbPicker(item, handle, verb, spec, onChange));
  }
  return section;
}
