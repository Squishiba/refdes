// Focus-preserving re-render helpers. A background poll that sees a new
// revision re-runs renderItem (app.js), and until now that replaced every
// control in the detail pane: the draft survived (drafts.js) but focus and
// the caret did not (in-prog-logs/browser-editor-edit-ui.md, "Focus is
// lost"). Editable controls now carry a stable `data-edit-key` naming the
// field they edit, so identity survives the rebuild: collectControls hands
// the old controls to the new render, which adopts the ones whose field is
// still there (editor.js updates them in place via controls.js), and
// captureFocus/restoreFocus carry focus and the selection across. Pure DOM
// logic -- no fetches, no framework -- small enough to reason about without
// a browser.

export function collectControls(container) {
  // Identity is attribute equality, not a CSS attribute selector: a field
  // name may hold characters that are not valid inside a selector.
  const controls = new Map();
  for (const node of container.querySelectorAll('[data-edit-key]')) {
    controls.set(node.getAttribute('data-edit-key'), node);
  }
  return controls;
}

export function captureFocus(container) {
  const active = document.activeElement;
  if (!active || active === document.body || !container.contains(active)) return null;
  const key = active.getAttribute('data-edit-key');
  if (!key) return null;
  const snap = { key };
  try {
    // selectionStart is null on control types that have no selection; the
    // restore then does focus only.
    snap.start = active.selectionStart;
    snap.end = active.selectionEnd;
  } catch (_) {
    // a control without a selection range: focus alone is enough
  }
  return snap;
}

export function restoreFocus(container, snap) {
  if (!snap) return;
  for (const node of container.querySelectorAll('[data-edit-key]')) {
    if (node.getAttribute('data-edit-key') !== snap.key) continue;
    node.focus();
    if (typeof snap.start === 'number') {
      try {
        node.setSelectionRange(snap.start, snap.end);
      } catch (_) {
        // the replacement control may not support a range; focus still holds
      }
    }
    return;
  }
  // The field is gone from the new view (read-only now, or removed): focus
  // is not restored, which is the honest outcome for a vanished control.
}
