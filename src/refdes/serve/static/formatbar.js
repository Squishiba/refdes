// The formatting bar's body-text mutation layer
// (in-prog-logs/editor-format-toolbar-design-20261029.md §B, slice 1).
//
// The bar inserts markdown through the same textarea pipeline as typing:
// Case A uses `execCommand('insertText')` so the native input event fires and
// the draft/panel listeners see one ordinary insertion; Case B splices
// `.value` and dispatches one synthetic input event. The shared fallback flag
// is live-calc's session key, so a browser that has proven `insertText`
// broken for the panel stands the bar down too.

const FALLBACK_KEY = 'refdes.live-calc.fallback';
const FALLBACK_NOTE = 'Undo may need more than one step in this browser.';
const TABLE = '| a | b |\n|---|---|\n|   |   |';
const FENCE = new RegExp('^\\x60{3}(calc[^\\n]*)?[ \\t]*\\r?$', 'gm');
const HEADING = new RegExp('^(#{1,6})\\s+([\\s\\S]*)$');
const URL = new RegExp('^https?:\\/\\/', 'i');

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function readFallbackFlag() {
  try {
    return sessionStorage.getItem(FALLBACK_KEY) === 'on';
  } catch (_) {
    return false;
  }
}

function writeFallbackFlag() {
  try {
    sessionStorage.setItem(FALLBACK_KEY, 'on');
  } catch (_) {
    /* the one-line note still shows; only persistence is lost */
  }
}

function clamp(value, length) {
  if (typeof value !== 'number' || Number.isNaN(value)) return length;
  return Math.max(0, Math.min(length, value));
}

function selectionIn(area) {
  const length = area.value.length;
  const start = clamp(area.selectionStart, length);
  const end = Math.max(start, clamp(area.selectionEnd, length));
  return { start, end };
}

function setSelection(area, start, end) {
  const length = area.value.length;
  const a = clamp(start, length);
  const b = Math.max(a, clamp(end, length));
  area.setSelectionRange(a, b);
}

export function applyEdit(area, start, end, text, selStart, selEnd, opts = {}) {
  if (opts.isSaving && opts.isSaving()) return false;

  const length = area.value.length;
  const from = clamp(start, length);
  const to = Math.max(from, clamp(end, length));

  if (!readFallbackFlag()) {
    try {
      area.focus();
      setSelection(area, from, to);
      if (document.execCommand('insertText', false, text) === true) {
        setSelection(area, selStart, selEnd);
        return true;
      }
    } catch (_) {
      /* Case A is best-effort; any throw is treated as a proven failure. */
    }
    writeFallbackFlag();
    if (opts.fallback) opts.fallback();
  }

  area.value = area.value.slice(0, from) + text + area.value.slice(to);
  setSelection(area, selStart, selEnd);
  area.focus();
  area.dispatchEvent(new Event('input', { bubbles: true }));
  return 'splice';
}

function lineRange(text, caret) {
  const start = text.lastIndexOf('\n', Math.max(0, caret - 1)) + 1;
  const end = text.indexOf('\n', start);
  return [start, end === -1 ? text.length : end];
}

function expandedLineRange(text, start, end) {
  const [lineStart] = lineRange(text, start);
  const probe = end > start ? end - 1 : start;
  const [, lineEnd] = lineRange(text, probe);
  return [lineStart, lineEnd];
}

function fenceBlocks(text) {
  const blocks = [];
  let opened = null;
  FENCE.lastIndex = 0;
  let match;
  while ((match = FENCE.exec(text)) !== null) {
    if (opened === null && match[1]) {
      opened = match.index + match[0].length;
    } else if (opened !== null && !match[1]) {
      blocks.push({
        start: opened,
        end: match.index,
        endLine: match.index + match[0].length,
      });
      opened = null;
    }
  }
  return blocks;
}

function fenceInsertAfter(text, caret) {
  for (const block of fenceBlocks(text)) {
    if (caret >= block.start && caret < block.end) return block.endLine;
  }
  return null;
}

export function blockInsertPlan(area, text, start, end) {
  const value = area.value;
  const current = selectionIn(area);
  let from = typeof start === 'number' ? clamp(start, value.length) : current.start;
  let to = typeof end === 'number' ? Math.max(from, clamp(end, value.length)) : current.end;
  const afterFence = fenceInsertAfter(value, from);
  if (afterFence !== null) {
    from = afterFence;
    to = afterFence;
  }
  const before = value.slice(0, from);
  const after = value.slice(to);
  const open = before === '' || before.endsWith('\n\n') ? '' : '\n\n';
  const close = after === '' || after.startsWith('\n\n') ? '' : '\n\n';
  const chunk = open + text + close;
  return {
    start: from,
    end: to,
    open,
    chunk,
    caret: before.length + chunk.length,
  };
}

function markerRuns(line, marker) {
  const runs = [];
  let i = 0;
  while (i < line.length) {
    if (line.startsWith(marker, i)) {
      let length = 0;
      while (line.startsWith(marker, i + length)) length += marker.length;
      runs.push({ start: i, length });
      i += length;
    } else {
      i += 1;
    }
  }
  return runs;
}

function unwrapInlineRange(text, caret, marker) {
  const [lineStart, lineEnd] = lineRange(text, caret);
  const line = text.slice(lineStart, lineEnd);
  const runs = markerRuns(line, marker).filter((run) => run.length === marker.length);
  let left = null;
  for (const run of runs) {
    if (run.start + marker.length <= caret - lineStart) left = run;
  }
  if (!left) return null;
  const right = runs.find((run) => run.start >= caret - lineStart);
  if (!right) return null;
  const start = lineStart + left.start;
  const openEnd = start + marker.length;
  const closeStart = lineStart + right.start;
  const end = closeStart + marker.length;
  if (!(openEnd <= caret && caret <= closeStart)) return null;
  const inner = text.slice(openEnd, closeStart);
  return { start, end, inner, selectStart: start, selectEnd: start + inner.length };
}

function applyInline(area, marker, placeholder, opts) {
  const text = area.value;
  const { start, end } = selectionIn(area);
  if (start === end) {
    const off = unwrapInlineRange(text, start, marker);
    if (off) {
      applyEdit(area, off.start, off.end, off.inner, off.selectStart, off.selectEnd, opts);
      return;
    }
    const chunk = marker + placeholder + marker;
    applyEdit(
      area,
      start,
      end,
      chunk,
      start + marker.length,
      start + marker.length + placeholder.length,
      opts,
    );
    return;
  }

  const chosen = text.slice(start, end);
  if (chosen.length >= marker.length * 2
    && chosen.startsWith(marker)
    && chosen.endsWith(marker)) {
    const inner = chosen.slice(marker.length, chosen.length - marker.length);
    applyEdit(area, start, end, inner, start, start + inner.length, opts);
    return;
  }

  const chunk = marker + chosen + marker;
  applyEdit(area, start, end, chunk, start + marker.length, start + marker.length + chosen.length, opts);
}

function applyHeading(area, opts) {
  const text = area.value;
  const { start } = selectionIn(area);
  const [lineStart, lineEnd] = lineRange(text, start);
  const line = text.slice(lineStart, lineEnd);
  const match = line.match(HEADING);
  let replacement;
  let caret;
  if (!match) {
    replacement = '# ' + line;
    caret = 1;
  } else if (match[1].length < 6) {
    const hashes = '#'.repeat(match[1].length + 1);
    replacement = hashes + ' ' + match[2];
    caret = hashes.length + 1;
  } else {
    replacement = match[2];
    caret = 0;
  }
  applyEdit(area, lineStart, lineEnd, replacement, lineStart + caret, lineStart + caret, opts);
}

function applyLineMarker(area, marker, pattern, opts, numbered = false) {
  const text = area.value;
  const { start, end } = selectionIn(area);
  const [lineStart, lineEnd] = expandedLineRange(text, start, end);
  const lines = text.slice(lineStart, lineEnd).split('\n');
  const allFormatted = lines.every((line) => pattern.test(line));
  const replacement = allFormatted
    ? lines.map((line) => line.replace(pattern, ''))
    : lines.map((line, index) => (numbered ? `${index + 1}. ${line}` : marker + line));
  const textReplacement = replacement.join('\n');
  applyEdit(
    area,
    lineStart,
    lineEnd,
    textReplacement,
    lineStart,
    lineStart + textReplacement.length,
    opts,
  );
}

function linkRange(text, caret) {
  const pair = text.lastIndexOf('](', Math.max(0, caret - 1));
  if (pair < 0) return null;
  const open = text.lastIndexOf('[', pair);
  const close = text.indexOf(')', pair + 2);
  if (open < 0 || close < 0) return null;
  if (!(pair < caret && caret <= close)) return null;
  const inner = text.slice(open + 1, pair);
  return {
    start: open,
    end: close + 1,
    replacement: inner,
    selectStart: open,
    selectEnd: open + inner.length,
  };
}

function applyLink(area, opts) {
  const text = area.value;
  const { start, end } = selectionIn(area);
  if (start === end) {
    const off = linkRange(text, start);
    if (off) {
      applyEdit(area, off.start, off.end, off.replacement, off.selectStart, off.selectEnd, opts);
      return;
    }
    const chunk = '[link text](url)';
    applyEdit(area, start, end, chunk, start + 12, start + 15, opts);
    return;
  }

  const chosen = text.slice(start, end);
  if (URL.test(chosen)) {
    const chunk = `[link text](${chosen})`;
    applyEdit(area, start, end, chunk, start + 1, start + 10, opts);
  } else {
    const chunk = `[${chosen}](url)`;
    const urlStart = start + chosen.length + 3;
    applyEdit(area, start, end, chunk, urlStart, urlStart + 3, opts);
  }
}

function applyTable(area, opts) {
  const plan = blockInsertPlan(area, TABLE);
  const textStart = plan.start + plan.open.length;
  applyEdit(area, plan.start, plan.end, plan.chunk, textStart + 2, textStart + 3, opts);
}

function applyRule(area, opts) {
  const plan = blockInsertPlan(area, '---');
  applyEdit(area, plan.start, plan.end, plan.chunk, plan.caret, plan.caret, opts);
}

const OPS = {
  bold: (area, opts) => applyInline(area, '**', 'bold text', opts),
  italic: (area, opts) => applyInline(area, '*', 'italic text', opts),
  strike: (area, opts) => applyInline(area, '~~', 'text', opts),
  code: (area, opts) => applyInline(area, '`', 'code', opts),
  heading: applyHeading,
  list: (area, opts) => applyLineMarker(area, '- ', /^\s*[-*+]\s+/, opts),
  numbered: (area, opts) => applyLineMarker(area, '1. ', /^\s*\d+\.\s+/, opts, true),
  quote: (area, opts) => applyLineMarker(area, '> ', /^\s*>\s?/, opts),
  link: applyLink,
  table: applyTable,
  hr: applyRule,
};

export const SHORTCUTS = [
  {
    op: 'bold',
    label: 'Bold',
    match: (event) => (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key).toLowerCase() === 'b',
  },
  {
    op: 'italic',
    label: 'Italic',
    match: (event) => (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key).toLowerCase() === 'i',
  },
  {
    op: 'link',
    label: 'Link',
    match: (event) => (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key).toLowerCase() === 'k',
  },
  {
    op: 'strike',
    label: 'Strikethrough',
    match: (event) => event.altKey && event.shiftKey && String(event.code) === 'Digit5',
  },
  {
    op: 'code',
    label: 'Code',
    match: (event) => (event.ctrlKey || event.metaKey) && event.altKey && !event.shiftKey
      && String(event.key).toLowerCase() === 'c',
  },
];

const BUTTONS = [
  ['bold', 'B', 'Bold'],
  ['italic', 'I', 'Italic'],
  ['strike', 'S', 'Strikethrough'],
  ['code', 'code', 'Code'],
  ['heading', 'H', 'Heading'],
  ['list', '•', 'Bulleted list'],
  ['numbered', '1.', 'Numbered list'],
  ['quote', '❝', 'Block quote'],
  ['link', 'Link', 'Link'],
  ['table', 'Table', 'Table'],
  ['hr', 'HR', 'Horizontal rule'],
];

export function createFormatBar(handle, { isSaving = () => false } = {}) {
  void handle;
  const node = el('div', 'format-bar');
  const core = el('div', 'fmt-core');
  node.appendChild(core);
  const note = el('p', 'format-bar-note warn', FALLBACK_NOTE);
  note.hidden = !readFallbackFlag();
  node.appendChild(note);

  let area = null;
  let boundArea = null;
  let boundHandler = null;

  function showFallbackNote() {
    note.hidden = false;
  }

  function run(op) {
    if (!area || (isSaving && isSaving())) return;
    OPS[op](area, { isSaving, fallback: showFallbackNote });
  }

  for (const [op, label, aria] of BUTTONS) {
    const button = el('button', `fmt-btn fmt-${op}`, label);
    button.type = 'button';
    button.setAttribute('aria-label', aria);
    button.addEventListener('mousedown', (event) => event.preventDefault());
    button.addEventListener('click', () => run(op));
    core.appendChild(button);
  }

  function detach() {
    if (boundArea && boundHandler) boundArea.removeEventListener('keydown', boundHandler);
    boundArea = null;
    boundHandler = null;
  }

  const ctrl = {
    node,
    attach(areaNode) {
      const previous = areaNode._refdesFormatBarCtl;
      if (previous && previous !== ctrl) previous.detach();
      detach();
      area = areaNode;
      boundArea = areaNode;
      boundHandler = (event) => {
        if (isSaving && isSaving()) return;
        const shortcut = SHORTCUTS.find((entry) => entry.match(event));
        if (!shortcut) return;
        event.preventDefault();
        run(shortcut.op);
      };
      areaNode.addEventListener('keydown', boundHandler);
      areaNode._refdesFormatBarCtl = ctrl;
    },
    detach,
  };
  node._refdesFormatBar = ctrl;
  return ctrl;
}
