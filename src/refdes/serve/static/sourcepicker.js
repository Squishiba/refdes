// A cited file -> key or page/candidate -> confirm picker. Python reads and composes
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
  let pageView = null;

  function message(value, kind = 'muted') {
    note.textContent = value;
    note.className = `source-note ${kind}`;
  }

  function clearAfterFile() {
    rowRequest += 1;
    proposalRequest += 1;
    rows.textContent = '';
    confirm.textContent = '';
    pageView = null;
    message('');
  }

  function showConfirm(path, key, pdf = null) {
    proposalRequest += 1;
    const request = proposalRequest;
    confirm.textContent = '';
    confirm.appendChild(el('p', 'muted', 'Reading the selected value…'));
    message('');
    const selection = pdf
      ? `&page=${pdf.payload.page}&row=${pdf.row.index}&token=${pdf.token.index}&sha256=${encodeURIComponent(pdf.payload.sha256)}`
      : '';
    if (pdf) highlightPdf(pdf.payload, pdf.row, pdf.token);

    // The first proposal supplies the row, proposed name and unit suggestions.
    // Its line is deliberately null because no unit has been chosen.
    api(`${base}/propose?path=${encodeURIComponent(path)}&key=${encodeURIComponent(key)}${selection}`)
      .then((initial) => {
        if (request !== proposalRequest) return;
        confirm.textContent = '';
        const entry = initial.entry;
        confirm.appendChild(el('h4', null, 'Confirm source value'));
        if (!pdf) confirm.appendChild(fact('Key', entry.key));
        confirm.appendChild(fact(pdf ? 'Candidate token' : 'Raw cell text', entry.raw));
        confirm.appendChild(fact('Canonical decimal', entry.value));
        if (pdf) {
          confirm.appendChild(fact('Page', entry.page));
          const quoted = el('div', 'source-quoted');
          quoted.appendChild(el('span', 'source-label', 'Whole row'));
          const text = el('span', 'source-value');
          for (const token of entry.row.tokens) {
            if (text.childNodes.length) text.appendChild(document.createTextNode(' '));
            text.appendChild(el(token.index === entry.token ? 'mark' : 'span', null, token.text));
          }
          quoted.appendChild(text);
          confirm.appendChild(quoted);
          confirm.appendChild(fact('Quoted row to record', entry.quoted));
          confirm.appendChild(fact('Column header guess', entry.header_guess || 'none'));
          confirm.appendChild(candidateList(pdf.payload, entry.row));
        } else {
          confirm.appendChild(fact('Line', entry.line));
        }
        const context = el('div', 'source-context');
        context.appendChild(el('span', 'source-label', 'Other columns'));
        for (const column of entry.context || []) context.appendChild(fact(column.name, column.text));
        if (!entry.context || !entry.context.length) context.appendChild(el('span', 'muted', 'none'));
        if (!pdf) confirm.appendChild(context);
        const pinned = fact('Pinned value', entry.pinned || 'none');
        const changed = el('p', 'source-changed warn', entry.changed ? 'changed since the pinned value' : '');
        confirm.appendChild(pinned);
        confirm.appendChild(changed);

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
        const keyInput = pdf ? el('input', 'source-key-input') : null;
        if (keyInput) {
          const keyLabel = el('label', 'source-input-label', 'Source key');
          keyInput.type = 'text';
          keyInput.value = initial.key;
          keyLabel.appendChild(keyInput);
          confirm.appendChild(keyLabel);
          keyInput.addEventListener('input', updateProposal);
        }

        const error = el('p', 'source-error bad');
        confirm.appendChild(error);
        const button = el('button', 'btn source-accept', 'Accept and save');
        button.type = 'button';
        button.disabled = true;
        confirm.appendChild(button);
        if (initial.accept_supported === false) confirm.appendChild(el('p', 'source-unavailable muted', initial.accept_reason));
        if (!accept) confirm.appendChild(el('p', 'muted', (item.edit && item.edit.body && item.edit.body.reason) || 'This body is read only.'));
        let current = null;
        let busy = false;
        let inserted = false;

        function updateProposal() {
          const chosenUnit = unit.value.trim();
          const chosenName = name.value.trim();
          const chosenKey = keyInput ? keyInput.value.trim() : key;
          const ticket = ++proposalRequest;
          current = null;
          line.textContent = 'Checking the proposed line…';
          button.disabled = true;
          error.textContent = '';
          if (pdf) {
            pinned.querySelector('.source-value').textContent = 'not checked for this key yet';
            changed.textContent = '';
          }
          if (!chosenUnit || !chosenName || !chosenKey || busy || inserted) {
            line.textContent = 'Choose a unit and variable name to see the line.';
            // Still read the pin for a PDF key while the unit is empty. No line is
            // complete until the author supplies the unit.
            if (!pdf || !chosenName || !chosenKey || busy || inserted) return;
          }
          api(`${base}/propose?path=${encodeURIComponent(path)}&key=${encodeURIComponent(chosenKey)}&unit=${encodeURIComponent(chosenUnit)}&name=${encodeURIComponent(chosenName)}${selection}`)
            .then((proposal) => {
              if (ticket !== proposalRequest) return;
              current = proposal.complete ? proposal : null;
              line.textContent = proposal.line || proposal.reason || '';
              pinned.querySelector('.source-value').textContent = proposal.entry.pinned || 'none';
              changed.textContent = proposal.entry.changed ? 'changed since the pinned value' : '';
              button.disabled = !accept || !current || !unit.value.trim() || proposal.accept_supported === false || busy || inserted;
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
          if (!accept || !current || !unit.value.trim() || current.accept_supported === false || busy || inserted) return;
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
            button.disabled = !current || !unit.value.trim() || current.accept_supported === false;
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

  function candidateList(payload, row) {
    const list = el('div', 'source-candidates');
    list.appendChild(el('span', 'source-label', 'Numeric candidates (choose one)'));
    for (const token of row.tokens.filter((token) => token.candidate)) {
      const choice = el('button', 'btn source-candidate', `${token.text} — column header guess: ${token.header_guess || 'none'}`);
      choice.type = 'button';
      choice.addEventListener('click', () => showConfirm(payload.path, '', { payload, row, token }));
      list.appendChild(choice);
    }
    return list;
  }

  function highlightPdf(payload, row, token) {
    if (!pageView) return;
    for (const old of pageView.querySelectorAll('.source-page-highlight')) old.remove();
    const [left, bottom, right, top] = payload.page_box;
    // Row grouping tolerates half a font size; the band includes that tolerance.
    const sizes = payload.spans.filter((span) => Math.abs(span.y - row.y) <= span.size / 2).map((span) => span.size);
    const size = Math.max(9, ...sizes);
    const band = el('div', 'source-page-highlight source-page-row-highlight');
    band.style.left = '0';
    band.style.top = `${top - row.y - size * 1.5}px`;
    band.style.width = `${right - left}px`;
    band.style.height = `${size * 2}px`;
    pageView.appendChild(band);
    const cell = el('div', 'source-page-highlight source-page-token-highlight');
    cell.style.left = `${token.x - left}px`;
    cell.style.top = `${top - row.y - size}px`;
    cell.style.width = `${Math.max(token.width, 2)}px`;
    cell.style.height = `${size * 1.5}px`;
    pageView.appendChild(cell);
    band.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function showPage(path, page = null) {
    const request = ++rowRequest;
    proposalRequest += 1;
    confirm.textContent = '';
    rows.textContent = '';
    pageView = null;
    rows.appendChild(el('p', 'muted', 'Reading PDF page…'));
    message('');
    // Omit page initially: Python chooses the cited page or resolved section.
    api(`${base}/page?path=${encodeURIComponent(path)}${page === null ? '' : `&page=${page}`}`)
      .then((payload) => {
        if (request !== rowRequest) return;
        rows.textContent = '';
        const nav = el('div', 'source-page-nav');
        for (const [label, target] of [['Previous page', payload.prev], ['Next page', payload.next]]) {
          const button = el('button', 'btn', label);
          button.type = 'button';
          button.disabled = target === null;
          button.addEventListener('click', () => showPage(path, target));
          nav.appendChild(button);
        }
        nav.appendChild(el('span', null, `Page ${payload.page} of ${payload.pages} (opened from ${payload.open_at.from})`));
        rows.appendChild(nav);
        if (payload.cited.detail) rows.appendChild(el('p', 'banner warn', payload.cited.detail));
        if (payload.drifted) rows.appendChild(el('p', 'banner warn', 'PDF bytes changed since the pin. This view shows the live file; the build uses pinned values.'));
        if (payload.detail) rows.appendChild(el('p', payload.too_dense || !payload.candidate_count ? 'banner bad' : 'banner warn', payload.detail));
        if (payload.too_dense) return;
        rows.appendChild(el('p', 'muted', 'Positioned-text reconstruction: no graphics or original fonts; text widths are estimated. Verify the highlighted row and token.'));
        if (payload.spans.length) {
          const viewport = el('div', 'source-page-viewport');
          pageView = el('div', 'source-page');
          pageView.setAttribute('aria-label', `Text reconstruction of PDF page ${payload.page}`);
          const [left, bottom, right, top] = payload.page_box;
          pageView.style.width = `${right - left}px`;
          pageView.style.height = `${top - bottom}px`;
          for (const span of payload.spans) {
            const run = el('span', 'source-page-span', span.text);
            run.style.left = `${span.x - left}px`;
            run.style.top = `${top - span.y}px`;
            run.style.fontSize = `${span.size}px`;
            pageView.appendChild(run);
          }
          viewport.appendChild(pageView);
          rows.appendChild(viewport);
        }
        const candidates = el('div', 'source-row-list');
        for (const row of payload.rows.filter((row) => row.candidate_count)) {
          const group = el('div', 'source-pdf-row');
          group.appendChild(el('p', 'source-preview', row.text));
          group.appendChild(candidateList(payload, row));
          candidates.appendChild(group);
        }
        // Even a single candidate requires a click. Nothing calls showConfirm here.
        if (payload.candidate_count) rows.appendChild(candidates);
      })
      .catch((err) => {
        if (request !== rowRequest) return;
        rows.textContent = '';
        pageView = null;
        rows.appendChild(el('p', 'banner bad', err.message));
        const retry = el('button', 'btn', 'Retry page');
        retry.type = 'button';
        retry.addEventListener('click', () => showPage(path, page));
        rows.appendChild(retry);
      });
  }

  files.appendChild(el('p', 'muted', 'Loading cited files…'));
  api(base)
    .then((payload) => {
      files.textContent = '';
      const offered = (payload.files || []).filter((file) => file.browse === 'rows' || file.browse === 'pages');
      if (!offered.length) {
        files.appendChild(el('p', 'muted', 'This item cites no browsable CSV or PDF. Add a citation to this same item in its YAML, then reopen the picker:'));
        files.appendChild(el('pre', 'source-empty', 'citations:\n  - path: analysis/your-file.csv\n  - path: datasheets/your-file.pdf'));
      }
      for (const file of offered) {
        const choose = el('button', 'btn source-file', file.path);
        choose.type = 'button';
        choose.addEventListener('click', () => {
          selectedPath = file.path;
          clearAfterFile();
          if (file.browse === 'pages') {
            showPage(file.path);
            return;
          }
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
    })
    .catch((err) => {
      files.textContent = '';
      files.appendChild(el('p', 'banner bad', err.message));
    });
  return section;
}
