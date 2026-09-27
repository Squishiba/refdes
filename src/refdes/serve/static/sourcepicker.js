// A cited file -> key -> confirm picker. Python reads the file and composes
// the calc line; this module displays its answers and asks the author for a
// unit before sending the line and pin through the editor's body save.
import { api } from './api.js';

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fact(label, value) {
  const row = el('div', 'source-fact');
  row.appendChild(el('span', 'source-label', label));
  row.appendChild(el('span', 'source-value', String(value)));
  return row;
}

export function createSourcePicker(item, handle, accept) {
  const section = el('div', 'source-picker');
  section.appendChild(el('h3', null, 'Insert source value'));
  const files = el('div', 'source-files');
  const rows = el('div', 'source-rows');
  const rowList = el('div', 'source-row-list');
  const confirm = el('div', 'source-confirm');
  const note = el('p', 'source-note muted');
  section.appendChild(files);
  section.appendChild(rows);
  section.appendChild(confirm);
  section.appendChild(note);

  const base = `/api/item/${encodeURIComponent(handle)}/sources`;
  let selectedPath = '';
  let rowRequest = 0;
  let proposalRequest = 0;

  function message(value, kind = 'muted') {
    note.textContent = value;
    note.className = `source-note ${kind}`;
  }

  function clearAfterFile() {
    rowRequest += 1;
    proposalRequest += 1;
    rows.textContent = '';
    confirm.textContent = '';
    message('');
  }

  function showConfirm(path, key) {
    proposalRequest += 1;
    const request = proposalRequest;
    confirm.textContent = '';
    confirm.appendChild(el('p', 'muted', 'Reading the row…'));
    message('');

    // The first proposal supplies the row, proposed name and unit suggestions.
    // Its line is deliberately null because no unit has been chosen.
    api(`${base}/propose?path=${encodeURIComponent(path)}&key=${encodeURIComponent(key)}`)
      .then((initial) => {
        if (request !== proposalRequest) return;
        confirm.textContent = '';
        const entry = initial.entry;
        confirm.appendChild(el('h4', null, 'Confirm source value'));
        confirm.appendChild(fact('Key', entry.key));
        confirm.appendChild(fact('Raw cell text', entry.raw));
        confirm.appendChild(fact('Canonical decimal', entry.value));
        confirm.appendChild(fact('Line', entry.line));
        const context = el('div', 'source-context');
        context.appendChild(el('span', 'source-label', 'Other columns'));
        for (const column of entry.context || []) context.appendChild(fact(column.name, column.text));
        if (!entry.context || !entry.context.length) context.appendChild(el('span', 'muted', 'none'));
        confirm.appendChild(context);
        confirm.appendChild(fact('Pinned value', entry.pinned || 'none'));
        if (entry.changed) confirm.appendChild(el('p', 'source-changed warn', 'changed since the pinned value'));

        const composed = el('div', 'source-composed');
        composed.appendChild(el('span', 'source-label', 'Calc line'));
        const line = el('code', 'source-line', 'Choose a unit to see the line.');
        composed.appendChild(line);
        confirm.appendChild(composed);

        const unitLabel = el('label', 'source-input-label', 'Unit');
        const unit = el('input', 'source-unit');
        unit.type = 'text';
        unit.value = ''; // never pre-select a unit, including dimensionless 1
        unitLabel.appendChild(unit);
        confirm.appendChild(unitLabel);
        const suggestions = el('div', 'source-suggestions');
        suggestions.appendChild(el('span', 'muted', 'Suggestions: '));
        for (const value of initial.units || []) {
          const choice = el('button', 'btn source-suggestion', value);
          choice.type = 'button';
          choice.addEventListener('click', () => {
            unit.value = value;
            updateProposal();
          });
          suggestions.appendChild(choice);
        }
        confirm.appendChild(suggestions);

        const nameLabel = el('label', 'source-input-label', 'Variable name');
        const name = el('input', 'source-name');
        name.type = 'text';
        name.value = initial.name;
        nameLabel.appendChild(name);
        confirm.appendChild(nameLabel);

        const error = el('p', 'source-error bad');
        confirm.appendChild(error);
        const button = el('button', 'btn source-accept', 'Accept and save');
        button.type = 'button';
        button.disabled = true;
        confirm.appendChild(button);
        if (!accept) confirm.appendChild(el('p', 'muted', (item.edit && item.edit.body && item.edit.body.reason) || 'This body is read only.'));
        let current = null;
        let busy = false;
        let inserted = false;

        function updateProposal() {
          const chosenUnit = unit.value.trim();
          const chosenName = name.value.trim();
          const ticket = ++proposalRequest;
          current = null;
          line.textContent = 'Checking the proposed line…';
          button.disabled = true;
          error.textContent = '';
          if (!chosenUnit || !chosenName || busy || inserted) {
            line.textContent = 'Choose a unit and variable name to see the line.';
            return;
          }
          api(`${base}/propose?path=${encodeURIComponent(path)}&key=${encodeURIComponent(key)}&unit=${encodeURIComponent(chosenUnit)}&name=${encodeURIComponent(chosenName)}`)
            .then((proposal) => {
              if (ticket !== proposalRequest) return;
              current = proposal.complete ? proposal : null;
              line.textContent = proposal.line || proposal.reason || '';
              button.disabled = !accept || !current || !unit.value.trim() || busy || inserted;
            })
            .catch((err) => {
              if (ticket !== proposalRequest) return;
              line.textContent = 'No valid line yet.';
              error.textContent = err.message;
            });
        }

        unit.addEventListener('input', updateProposal);
        name.addEventListener('input', updateProposal);
        button.addEventListener('click', async () => {
          if (!accept || !current || !unit.value.trim() || busy || inserted) return;
          busy = true;
          button.disabled = true;
          error.textContent = '';
          try {
            // accept places the server's line through setDraftBody, attaches
            // the pin to that body op and uses the existing Save path.
            const saved = await accept(current);
            inserted = true;
            if (!saved) error.textContent = 'The draft is still here. Use Save or the conflict controls to retry.';
          } catch (err) {
            error.textContent = err.message;
            busy = false;
            button.disabled = !current || !unit.value.trim();
          }
        });
      })
      .catch((err) => {
        if (request !== proposalRequest) return;
        confirm.textContent = '';
        confirm.appendChild(el('p', 'banner bad', err.message));
      });
  }

  function showRows(path, query = '') {
    const request = ++rowRequest;
    rowList.textContent = '';
    rowList.appendChild(el('p', 'muted', 'Reading keys…'));
    confirm.textContent = '';
    proposalRequest += 1;
    api(`${base}/entries?path=${encodeURIComponent(path)}&q=${encodeURIComponent(query)}`)
      .then((payload) => {
        if (request !== rowRequest) return;
        rowList.textContent = '';
        for (const problem of payload.problems || []) rowList.appendChild(el('p', 'banner bad', problem));
        if (payload.truncated) rowList.appendChild(el('p', 'banner', payload.truncation || 'The file was truncated.'));
        for (const entry of payload.entries || []) {
          const row = el('div', 'source-row');
          row.appendChild(el('span', 'source-key', entry.key || '(blank key)'));
          row.appendChild(el('span', 'source-preview muted', entry.raw));
          if (entry.problem) row.appendChild(el('span', 'bad', entry.problem));
          const pick = el('button', 'btn source-pick', 'Review');
          pick.type = 'button';
          pick.disabled = !entry.selectable;
          pick.addEventListener('click', () => showConfirm(path, entry.key));
          row.appendChild(pick);
          rowList.appendChild(row);
        }
        if (!payload.entries.length && !payload.problems.length) rowList.appendChild(el('p', 'muted', 'No keys match.'));
      })
      .catch((err) => {
        if (request !== rowRequest) return;
        rowList.textContent = '';
        rowList.appendChild(el('p', 'banner bad', err.message));
      });
  }

  files.appendChild(el('p', 'muted', 'Loading cited files…'));
  api(base)
    .then((payload) => {
      files.textContent = '';
      const offered = (payload.files || []).filter((file) => file.browse === 'rows');
      if (!offered.length) {
        files.appendChild(el('p', 'muted', 'This item cites no browsable CSV. Add a citation to this same item in its YAML, then reopen the picker:'));
        files.appendChild(el('pre', 'source-empty', 'citations:\n  - path: analysis/your-file.csv'));
      }
      for (const file of offered) {
        const choose = el('button', 'btn source-file', file.path);
        choose.type = 'button';
        choose.addEventListener('click', () => {
          selectedPath = file.path;
          clearAfterFile();
          const filter = el('input', 'source-filter');
          filter.type = 'search';
          filter.placeholder = 'Filter keys…';
          filter.addEventListener('input', () => showRows(selectedPath, filter.value));
          rows.appendChild(filter);
          rows.appendChild(rowList);
          showRows(file.path);
        });
        const row = el('div', 'source-file-row');
        row.appendChild(choose);
        row.appendChild(el('span', 'muted', file.state));
        if (file.detail) row.appendChild(el('span', 'source-detail', file.detail));
        for (const [key, value] of Object.entries(file.pinned_values || {})) {
          row.appendChild(el('span', 'source-pin muted', `${key}: ${value}`));
        }
        files.appendChild(row);
      }
      for (const problem of payload.problems || []) files.appendChild(el('p', 'banner bad', `${problem.path}: ${problem.problem}`));
      if ((payload.files || []).some((file) => file.browse !== 'rows')) {
        files.appendChild(el('p', 'muted', 'Page based sources use a separate picker.'));
      }
    })
    .catch((err) => {
      files.textContent = '';
      files.appendChild(el('p', 'banner bad', err.message));
    });
  return section;
}
