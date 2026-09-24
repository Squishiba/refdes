// The one field-control factory: the enum select and the text input the
// edit form builds from the server's `edit.fields` specs are built here, so
// the create form (create.js) reuses the identical control code instead of
// a second copy that could drift. The specs say what a control is; nothing
// here knows about schemas, drafts, or saving.

export function fieldControlNode(spec, value, onChange) {
  let node;
  if (spec && spec.control === 'select') {
    node = document.createElement('select');
    node.className = 'field-edit';
    for (const choice of spec.choices || []) {
      const option = document.createElement('option');
      option.textContent = choice;
      option.value = choice;
      node.appendChild(option);
    }
  } else {
    node = document.createElement('input');
    node.className = 'field-edit';
    node.type = 'text';
  }
  node.value = value === null || value === undefined ? '' : String(value);
  const commit = () => onChange(node);
  node.addEventListener('input', commit);
  node.addEventListener('change', commit);
  return node;
}
