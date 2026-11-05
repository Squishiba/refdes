"use strict";

const TEXT_LIMIT = 200;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

const blocksList = document.getElementById("blocks");
const cardsPane = document.getElementById("cards");
const countsLine = document.getElementById("summary-counts");

const state = { doc: null, selected: null, mtime: null };

function refFlags(ref) {
  const card = ref.card || {};
  const flags = [];
  const path = card.path || ref.path;
  if (ref.kind === "code_ref" || ref.kind === "file_ref") {
    if (card.error) flags.push(card.error + ": " + path);
    else if (card.exists === false) flags.push("file not found: " + path);
    if (card.in_range === false) flags.push("cited line past the file end");
    if (card.symbols_missing && card.symbols_missing.length > 0) {
      flags.push("not found near the cited line: " + card.symbols_missing.join(", "));
    }
  } else if (ref.kind === "command") {
    if (!card.known) flags.push("unknown command: " + (ref.command || ""));
  } else if (ref.kind === "link") {
    if (card.error) flags.push(card.error);
    if (!card.external) {
      if (card.target_exists === false) {
        flags.push("target page not found: " + (card.page || ref.target));
      }
      if (card.anchor_ok === false) flags.push("anchor not found: #" + card.anchor);
    }
  }
  return flags;
}

function blockLabel(block) {
  const span = el("span", "block-text");
  const text = block.text;
  let pos = 0;
  for (const ref of block.refs) {
    if (pos >= TEXT_LIMIT || ref.start >= TEXT_LIMIT) break;
    const a = Math.max(ref.start, pos);
    const b = Math.min(ref.end, TEXT_LIMIT);
    if (a > pos) span.appendChild(document.createTextNode(text.slice(pos, a)));
    span.appendChild(el("span", "refmark", text.slice(a, b)));
    pos = Math.max(pos, b);
  }
  if (pos < Math.min(text.length, TEXT_LIMIT)) {
    span.appendChild(document.createTextNode(text.slice(pos, TEXT_LIMIT)));
  }
  if (text.length > TEXT_LIMIT) span.appendChild(document.createTextNode(" …"));
  return span;
}

function codeWindow(lines, cited) {
  const pre = el("pre", "code");
  for (const line of lines) {
    const inCited = cited && line.n >= cited[0] && line.n <= cited[1];
    const row = el("div", "line" + (inCited ? " hl" : ""));
    row.appendChild(el("span", "n", String(line.n)));
    row.appendChild(el("span", "t", line.text));
    pre.appendChild(row);
  }
  return pre;
}

function renderCard(ref) {
  const card = ref.card || {};
  const box = el("article", "card");
  const head = el("div", "card-head");
  head.appendChild(el("span", "kind", ref.kind));
  let title = ref.raw;
  if (ref.kind === "code_ref" || ref.kind === "file_ref") title = card.path || ref.path;
  if (ref.kind === "command") title = ref.command;
  if (ref.kind === "link") title = ref.target;
  head.appendChild(el("span", "card-title", title));
  box.appendChild(head);
  for (const flag of refFlags(ref)) box.appendChild(el("div", "flag", "flag: " + flag));
  if (ref.kind === "code_ref" || ref.kind === "file_ref") {
    if (card.lines) box.appendChild(codeWindow(card.lines, card.cited));
    if (card.cited) {
      box.appendChild(el("div", "meta", "cited lines " + card.cited[0] + "-" + card.cited[1]));
    }
  } else if (ref.kind === "command") {
    box.appendChild(el("span", "badge " + (card.known ? "ok" : "bad"), card.known ? "known" : "unknown"));
    if (card.verbs && card.verbs.length > 0) {
      box.appendChild(el("div", "meta", "verbs: " + card.verbs.join(" ")));
    }
    if (card.help) box.appendChild(el("pre", "help", card.help));
  } else if (ref.kind === "link") {
    if (card.external) {
      box.appendChild(el("span", "badge", "external (plain text, never fetched)"));
      box.appendChild(el("div", "url", card.url || ref.target));
    } else {
      box.appendChild(
        el("span", "badge " + (card.target_exists ? "ok" : "bad"),
          card.target_exists ? "target exists" : "target missing")
      );
      box.appendChild(
        el("span", "badge " + (card.anchor_ok ? "ok" : "bad"),
          card.anchor_ok ? "anchor ok" : "anchor broken")
      );
      if (card.heading) box.appendChild(el("div", "meta", "heading: " + card.heading));
      if (card.excerpt && card.excerpt.length > 0) {
        box.appendChild(el("pre", "excerpt", card.excerpt.join("\n")));
      }
    }
  }
  return box;
}

function selectedBlock() {
  if (!state.doc) return null;
  for (const block of state.doc.blocks) {
    if (block.start_line === state.selected) return block;
  }
  return null;
}

function render() {
  const leftScroll = blocksList.scrollTop;
  const rightScroll = cardsPane.scrollTop;
  const pageScroll = window.scrollY;
  blocksList.textContent = "";
  cardsPane.textContent = "";
  const data = state.doc;
  if (!data) return;
  if (state.selected === null && data.blocks.length > 0) {
    state.selected = data.blocks[0].start_line;
  }
  let totalRefs = 0;
  let flaggedRefs = 0;
  for (const block of data.blocks) {
    let flagged = 0;
    for (const ref of block.refs) {
      if (refFlags(ref).length > 0) flagged += 1;
    }
    totalRefs += block.refs.length;
    flaggedRefs += flagged;
    const li = el("li", "block");
    li.dataset.start = String(block.start_line);
    li.tabIndex = 0;
    li.appendChild(el("span", "kind", block.kind));
    li.appendChild(el("span", "lines", block.start_line + "-" + block.end_line));
    if (flagged > 0) li.appendChild(el("span", "flagcount", String(flagged)));
    li.appendChild(blockLabel(block));
    if (block.start_line === state.selected) li.setAttribute("aria-current", "true");
    li.addEventListener("click", () => select(block.start_line));
    blocksList.appendChild(li);
  }
  countsLine.textContent =
    data.blocks.length + " blocks, " + totalRefs + " refs, " + flaggedRefs + " flagged";
  const block = selectedBlock();
  if (!block) {
    cardsPane.appendChild(el("p", "hint", "select a block to see its reference cards"));
  } else {
    cardsPane.appendChild(
      el("h2", "cards-title",
        "lines " + block.start_line + "-" + block.end_line +
        " · " + block.refs.length + " refs")
    );
    if (block.refs.length === 0) {
      cardsPane.appendChild(el("p", "hint", "this block makes no references"));
    }
    for (const ref of block.refs) cardsPane.appendChild(renderCard(ref));
  }
  blocksList.scrollTop = leftScroll;
  cardsPane.scrollTop = rightScroll;
  window.scrollTo(0, pageScroll);
}

function select(startLine) {
  state.selected = startLine;
  render();
}

function moveSelection(delta) {
  const blocks = state.doc ? state.doc.blocks : [];
  if (blocks.length === 0) return;
  let index = -1;
  for (let i = 0; i < blocks.length; i += 1) {
    if (blocks[i].start_line === state.selected) index = i;
  }
  if (index < 0) index = delta > 0 ? -1 : blocks.length;
  index = Math.min(blocks.length - 1, Math.max(0, index + delta));
  state.selected = blocks[index].start_line;
  render();
  const current = blocksList.querySelector('.block[aria-current="true"]');
  if (current) current.scrollIntoView({ block: "nearest" });
}

function keepSelectionAlive() {
  const blocks = state.doc ? state.doc.blocks : [];
  if (state.selected === null) return;
  for (const block of blocks) {
    if (block.start_line === state.selected) return;
  }
  let best = null;
  let bestGap = Infinity;
  for (const block of blocks) {
    const gap = Math.abs(block.start_line - state.selected);
    if (gap < bestGap) {
      bestGap = gap;
      best = block;
    }
  }
  state.selected = best ? best.start_line : null;
}

async function refreshDoc() {
  const response = await fetch("/api/doc");
  if (!response.ok) throw new Error("doc fetch failed: " + response.status);
  state.doc = await response.json();
  state.mtime = state.doc.mtime;
  keepSelectionAlive();
  render();
}

function showStartupFailure(err) {
  countsLine.textContent = "cannot reach the doc server: " + String(err) + " (still retrying)";
}

let inFlight = false;

async function tick() {
  if (inFlight) return;
  inFlight = true;
  try {
    const response = await fetch("/api/mtime");
    const data = await response.json();
    if (state.mtime !== null && data.mtime !== state.mtime) await refreshDoc();
  } catch (err) {
    /* the page is polling its own server; a blip is fine, the next tick retries */
  } finally {
    inFlight = false;
  }
}

document.addEventListener("keydown", (event) => {
  const tag = event.target ? event.target.tagName : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (event.key === "j" || event.key === "ArrowDown") {
    event.preventDefault();
    moveSelection(1);
  } else if (event.key === "k" || event.key === "ArrowUp") {
    event.preventDefault();
    moveSelection(-1);
  }
});

refreshDoc().catch(showStartupFailure);
setInterval(tick, 1500);
