// The editor font preference (in-prog-logs/editor-format-toolbar-design-20261029.md
// §D). It is deliberately a personal browser setting, not project state: the
// only persistence surface is localStorage under refdes.editor.font, and the
// only mutation surface is CSS custom properties on the body textarea. The
// popover controls family, size, and line height; every change applies live
// and persists immediately. Storage failures degrade to in-memory defaults
// instead of taking the editor down.

const STORAGE_KEY = 'refdes.editor.font';
const DEFAULT_FONT = Object.freeze({ family: 'mono', size: 12, lineHeight: 1.5 });
const FONT_STACKS = Object.freeze({
  mono: 'monospace',
  sans: 'system-ui, sans-serif',
  serif: 'Georgia, serif',
});
const SIZE_MIN = 11;
const SIZE_MAX = 20;
const LINE_HEIGHT_STEPS = Object.freeze({
  compact: 1.35,
  normal: 1.5,
  loose: 1.7,
});
const LINE_HEIGHT_VALUES = Object.freeze(Object.values(LINE_HEIGHT_STEPS));
const LINE_HEIGHT_KEYS = Object.freeze(
  Object.fromEntries(Object.entries(LINE_HEIGHT_STEPS).map(([key, value]) => [String(value), key]))
);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function defaultPreference() {
  return {
    family: DEFAULT_FONT.family,
    size: DEFAULT_FONT.size,
    lineHeight: DEFAULT_FONT.lineHeight,
  };
}

function storageNow() {
  try {
    return globalThis.localStorage;
  } catch (_) {
    return null;
  }
}

function normalizeSize(value, fallback) {
  if (typeof value === 'boolean' || value === null || value === '' || Array.isArray(value)) {
    return fallback;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(SIZE_MIN, Math.min(SIZE_MAX, Math.round(number)));
}

function normalizeLineHeight(value, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return LINE_HEIGHT_VALUES.includes(number) ? number : fallback;
}

function normalizePreference(raw) {
  const out = defaultPreference();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  if (Object.prototype.hasOwnProperty.call(FONT_STACKS, raw.family)) out.family = raw.family;
  out.size = normalizeSize(raw.size, out.size);
  out.lineHeight = normalizeLineHeight(raw.lineHeight, out.lineHeight);
  return out;
}

function loadPreference() {
  const storage = storageNow();
  try {
    const raw = storage ? storage.getItem(STORAGE_KEY) : null;
    if (!raw) return defaultPreference();
    return normalizePreference(JSON.parse(raw));
  } catch (_) {
    return defaultPreference();
  }
}

function savePreference(preference) {
  const storage = storageNow();
  try {
    if (storage) storage.setItem(STORAGE_KEY, JSON.stringify(preference));
  } catch (_) {
    // A private mode or quota failure costs persistence, not the live setting.
  }
}

function choice(label, cls, dataKey, dataValue, applyValue, current, onChoose) {
  const row = el('label', `${cls}-choice`);
  const input = el('input', `${cls} ${cls}-${dataValue}`);
  input.type = 'radio';
  input.checked = current === applyValue;
  input.dataset[dataKey] = String(dataValue);
  input.addEventListener('click', () => onChoose(applyValue));
  row.appendChild(input);
  row.appendChild(el('span', `font-sample font-sample-${dataValue}`, label));
  return { row, input };
}

export function createFontSetting() {
  let state = loadPreference();
  let bound = null;

  const node = el('div', 'font-setting');
  const toggle = el('button', 'btn font-setting-toggle', 'Font');
  toggle.type = 'button';
  toggle.setAttribute('aria-haspopup', 'dialog');
  toggle.setAttribute('aria-expanded', 'false');
  node.appendChild(toggle);

  const popover = el('div', 'font-setting-popover');
  popover.hidden = true;
  popover.setAttribute('role', 'dialog');
  popover.setAttribute('aria-label', 'Editor font setting');
  node.appendChild(popover);

  const familyBox = el('div', 'font-setting-section');
  familyBox.appendChild(el('span', 'font-setting-title', 'Family'));
  const familyInputs = [];
  for (const [value, label] of [
    ['mono', 'Mono'],
    ['sans', 'Sans'],
    ['serif', 'Serif'],
  ]) {
    const row = choice(label, 'font-family', 'family', value, value, state.family, setFamily);
    familyInputs.push(row.input);
    familyBox.appendChild(row.row);
  }
  popover.appendChild(familyBox);

  const sizeBox = el('div', 'font-setting-section');
  sizeBox.appendChild(el('span', 'font-setting-title', 'Size'));
  const sizeRow = el('div', 'font-size-row');
  const decrease = el('button', 'btn font-size-decrease', '-');
  const sizeValue = el('span', 'font-size-value', `${state.size}px`);
  const increase = el('button', 'btn font-size-increase', '+');
  decrease.type = 'button';
  increase.type = 'button';
  decrease.setAttribute('aria-label', 'Decrease font size');
  increase.setAttribute('aria-label', 'Increase font size');
  decrease.addEventListener('click', () => setSize(state.size - 1));
  increase.addEventListener('click', () => setSize(state.size + 1));
  sizeRow.appendChild(decrease);
  sizeRow.appendChild(sizeValue);
  sizeRow.appendChild(increase);
  sizeBox.appendChild(sizeRow);
  popover.appendChild(sizeBox);

  const lineHeightBox = el('div', 'font-setting-section');
  lineHeightBox.appendChild(el('span', 'font-setting-title', 'Line height'));
  const lineHeightInputs = [];
  for (const [value, label] of [
    ['compact', 'Compact'],
    ['normal', 'Normal'],
    ['loose', 'Loose'],
  ]) {
    const row = choice(label, 'font-line-height', 'lineHeight', value, LINE_HEIGHT_STEPS[value], state.lineHeight, setLineHeight);
    lineHeightInputs.push(row.input);
    lineHeightBox.appendChild(row.row);
  }
  popover.appendChild(lineHeightBox);

  const reset = el('button', 'btn font-reset', 'Reset to defaults');
  reset.type = 'button';
  reset.addEventListener('click', () => {
    state = defaultPreference();
    updateControls();
    persistAndApply();
  });
  popover.appendChild(reset);

  function setOpen(open) {
    popover.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  toggle.addEventListener('click', () => setOpen(popover.hidden));
  node.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !popover.hidden) {
      setOpen(false);
      toggle.focus();
    }
  });

  function updateControls() {
    for (const input of familyInputs) input.checked = input.dataset.family === state.family;
    for (const input of lineHeightInputs) {
      input.checked = input.dataset.lineHeight === LINE_HEIGHT_KEYS[String(state.lineHeight)];
    }
    sizeValue.textContent = `${state.size}px`;
    decrease.disabled = state.size <= SIZE_MIN;
    increase.disabled = state.size >= SIZE_MAX;
  }

  function persistAndApply() {
    savePreference(state);
    if (bound) applyTo(bound);
  }

  function setFamily(value) {
    if (!Object.prototype.hasOwnProperty.call(FONT_STACKS, value)) return;
    state = Object.assign({}, state, { family: value });
    updateControls();
    persistAndApply();
  }

  function setSize(value) {
    state = Object.assign({}, state, { size: normalizeSize(value, state.size) });
    updateControls();
    persistAndApply();
  }

  function setLineHeight(value) {
    state = Object.assign({}, state, { lineHeight: normalizeLineHeight(value, state.lineHeight) });
    updateControls();
    persistAndApply();
  }

  function applyTo(area) {
    bound = area;
    area.style.setProperty('--refdes-editor-font', FONT_STACKS[state.family]);
    area.style.setProperty('--refdes-editor-size', `${state.size}px`);
    area.style.setProperty('--refdes-editor-line-height', String(state.lineHeight));
  }

  updateControls();
  return {
    node,
    current: () => Object.assign({}, state),
    applyTo,
    setFamily,
    setSize,
    setLineHeight,
  };
}

export { DEFAULT_FONT, FONT_STACKS, STORAGE_KEY };
