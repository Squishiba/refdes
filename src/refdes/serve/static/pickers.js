// The shared candidate machinery for every picker that offers project items
// (in-prog-logs/editor-format-toolbar-design-20261029.md §C, slice 2): the
// link pickers (links.js) and the bar's `[[ID]]` reference picker
// (formatbar.js). One fetch through the same /api/items filter the list pane
// uses (one query language, one snapshot), one page size, one label shape,
// one display-id rule.
//
// The display rule is the surrogate-keys rule (docs/design/keys.md): rows
// carry the bare display id (`id`, falling back to the handle) and pickers
// show/speak that alone -- never the `@key` composite half.

import { api } from './api.js';

// The picker asks the list API for its full page (MAX_LIMIT in
// serve/filters.py) rather than the default 500. When even a full page is
// capped the notice says so, and says the filter searches only the fetched
// rows: the list API has no offset, so nothing a picker does can reach rows
// past the cap, and a notice promising a filter remedy would hide valid
// targets with false hope.
export const PICKER_LIMIT = 5000;

export function displayHalf(target) {
  const at = target.lastIndexOf('@');
  return at > 0 ? target.slice(0, at) : target;
}

export function displayId(row) {
  return String(row.id || row.handle);
}

export function rowLabel(row) {
  return `${displayId(row)} — ${row.title || ''}`;
}

export function matchesFilter(row, want) {
  return rowLabel(row).toLowerCase().includes(want);
}

// An empty declared list is not an empty candidate list: it is how the
// schema spells "unrestricted" -- model.Project.accepts_type says so in its
// docstring, build.resolve_links skips the type check for it, and the
// editor gate serves it as "any declared type" (the standard verb
// `log.blocked_by: []` is the live case). A picker asks for exactly what
// the server accepts: the declared types when there are any, the whole
// project when the list is empty.
export async function candidatesFor(types) {
  const base = `/api/items?limit=${PICKER_LIMIT}`;
  const queries = types && types.length
    ? types.map((type) => `${base}&type=${encodeURIComponent(type)}`)
    : [base];
  const out = [];
  let total = 0;
  for (const query of queries) {
    const payload = await api(query);
    const found = payload.items || [];
    total += payload.total ?? found.length;
    out.push(...found);
  }
  out.sort((a, b) => displayId(a).localeCompare(displayId(b)));
  return { items: out, total };
}
