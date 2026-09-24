// The one field-control factory: the enum select and the text input the
// edit form builds from the server's `edit.fields` specs are built here, so
// the create form (create.js) reuses the identical control code instead of
// a second copy that could drift. The specs say what a control is; nothing
// here knows about schemas, drafts, or saving. applyControl also re-binds an
// existing node, which is what lets a rebuild update a control in place
// instead of replacing it (see update.js).

export function fieldControlNode(spec, value, onChange) {
  const node = wantsSelect(spec)
    ? document.createElement('select')
    : document.createElement('input');
  node.className = 'field-edit';
  if (node.tagName === 'INPUT') node.type = 'text';
  return applyControl(node, spec, value, onChange);
}

// Bind -- or re-bind -- a control to a spec, a value and a change handler.
// Returns null when the node is the wrong kind of control for the spec, so
// the caller knows to create a fresh one instead. On a re-bind the previous
// commit listener is detached first: a re-render must not stack a second
// handler on the same node. The value is written only when it actually
// differs, so a rebuild landing mid-typing never fights the author's own
// keystrokes.
export function applyControl(node, spec, value, onChange) {
  if (!node || node.tagName !== (wantsSelect(spec) ? 'SELECT' : 'INPUT')) return null;
  if (node._refdesCommit) {
    node.removeEventListener('input', node._refdesCommit);
    node.removeEventListener('change', node._refdesCommit);
    node._refdesCommit = null;
  }
  if (node.tagName === 'SELECT') fillOptions(node, spec);
  const shown = value === null || value === undefined ? '' : String(value);
  if (node.value !== shown) node.value = shown;
  const commit = () => onChange(node);
  node._refdesCommit = commit;
  node.addEventListener('input', commit);
  node.addEventListener('change', commit);
  return node;
}

function wantsSelect(spec) {
  return Boolean(spec && spec.control === 'select');
}

function fillOptions(node, spec) {
  const choices = (spec && spec.choices) || [];
  const same = node.options.length === choices.length
    && Array.from(node.options).every((option, i) => option.value === String(choices[i]));
  if (same) return;
  node.textContent = '';
  for (const choice of choices) {
    const option = document.createElement('option');
    option.textContent = choice;
    option.value = choice;
    node.appendChild(option);
  }
}
