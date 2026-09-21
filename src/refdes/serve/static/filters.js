// Filter state lives in the URL: #/items?board=board-a&stage=open. The hash
// query carries exactly the same parameter names the /api/items endpoint
// takes, so a view is deep-linkable, survives reload, and the server's
// `filters` echo is the authority on what is active.

export const FILTER_PARAMS = [
  'q', 'type', 'board', 'workspace', 'tag', 'file',
  'stage', 'check', 'blocked', 'links_to', 'linked_from', 'missing_verb',
];

// Facets rendered in the sidebar, in order. The counts come from the server;
// the UI never counts anything itself.
export const FACETS = [
  ['type', 'Type'],
  ['board', 'Board'],
  ['workspace', 'Workspace'],
  ['stage', 'Coverage stage'],
  ['check', 'Check state'],
  ['blocked', 'Blocked'],
  ['tag', 'Tag'],
  ['file', 'Source file'],
];

export function parseFilters(hash) {
  const q = hash.indexOf('?');
  const params = new URLSearchParams(q === -1 ? '' : hash.slice(q + 1));
  const filters = {};
  for (const name of FILTER_PARAMS) {
    const value = params.get(name);
    if (value !== null && value !== '') filters[name] = value;
  }
  return filters;
}

export function filterQuery(filters) {
  const params = new URLSearchParams();
  for (const name of FILTER_PARAMS) {
    const value = filters[name];
    if (value !== undefined && value !== '') params.set(name, value);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export function itemsHref(filters) {
  return `#/items${filterQuery(filters)}`;
}

// One-click behavior on a facet value: set it; clicking the active value
// clears it. Free-text-ish params (q, links_to, ...) are edited in inputs.
export function withFacet(filters, name, value) {
  const next = { ...filters };
  if (next[name] === value) delete next[name];
  else next[name] = value;
  return next;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function facetBlock(name, label, filters, counts, onChange) {
  const block = el('div', 'facet');
  block.appendChild(el('h3', null, label));
  const values = Object.entries(counts || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  if (!values.length) block.appendChild(el('p', 'muted', 'none'));
  for (const [value, count] of values) {
    const button = el('button', 'facet-value');
    button.type = 'button';
    button.dataset.facet = name;
    button.dataset.value = value;
    if (filters[name] === value) button.classList.add('active');
    button.appendChild(el('span', 'facet-label', value));
    button.appendChild(el('span', 'facet-count', String(count)));
    button.addEventListener('click', () => onChange(withFacet(filters, name, value)));
    block.appendChild(button);
  }
  return block;
}

function textFilter(name, label, placeholder, filters, onChange) {
  const block = el('div', 'facet');
  block.appendChild(el('h3', null, label));
  const input = el('input', 'text-filter');
  input.type = 'text';
  input.placeholder = placeholder;
  input.value = filters[name] || '';
  input.setAttribute('aria-label', label);
  input.addEventListener('change', () => {
    const next = { ...filters };
    if (input.value.trim()) next[name] = input.value.trim();
    else delete next[name];
    onChange(next);
  });
  block.appendChild(input);
  return block;
}

export function renderSidebar(container, payload, filters, onChange) {
  container.textContent = '';
  container.appendChild(textFilter('q', 'Free text', 'title or tags', filters, onChange));
  for (const [name, label] of FACETS) {
    container.appendChild(facetBlock(name, label, filters, payload.facets[name], onChange));
  }
  container.appendChild(textFilter('links_to', 'Links to', 'item id or key', filters, onChange));
  container.appendChild(textFilter('linked_from', 'Linked from', 'item id or key', filters, onChange));
  container.appendChild(textFilter('missing_verb', 'Missing link verb', 'e.g. satisfies', filters, onChange));
  const clear = el('button', 'clear-filters');
  clear.type = 'button';
  clear.textContent = 'Clear all filters';
  clear.addEventListener('click', () => onChange({}));
  container.appendChild(clear);
}
