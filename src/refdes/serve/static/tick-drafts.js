// Tick drafts: the write pane's pending ticks before the save (design
// docs/design/thread-workbench-w5b-plan.md, §4 W5b.4 + §6 Q1/Q5/Q6/Q8, all
// RATIFIED 2026-11-06). One draft per tip, keyed by the tip's KEY (Q5a: the
// composite `DISPLAY-ID@key` is the identity, not its display half), shaped
// {revision, ticks: {taskId: wantedState}}. The module is PURE by design: no
// DOM, no network, no page globals -- the storage object (the page's per-tab
// session mirror) is INJECTED, so these rules run headless under test. It
// reuses the editor's item-draft persistence RULES, not its module: page
// memory is the live copy; the mirror survives a reload and dies with the
// tab; an unreadable mirror is never a clean slate -- its bytes are preserved
// under a corrupt key of this module's own, re-armed on every load, until an
// explicit discard; and a storage fault costs persistence, never editing. The
// prefix is its own, so a tick draft can never read or write an item draft.
//
// createTickDrafts(storage) -> {
//   get(tipKey), setTick(tipKey, taskId, wantedState, originalState),
//   clearTick(tipKey, taskId), pendingCount(tipKey), pendingTicks(tipKey),
//   setRevision(tipKey, revision), revision(tipKey), discard(tipKey),
//   corrupt(tipKey), counts(), persistent()
// }

const TICK_PREFIX = 'refdes.tickdraft.v1.';
const CORRUPT_PREFIX = 'refdes.tickdraft.corrupt.v1.';

function encodeKey(prefix, tipKey) {
  return prefix + encodeURIComponent(tipKey);
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function decodeEnvelope(stored) {
  // The recovery copy is an {raw, reason} envelope, so a reload names the
  // same damage the first page saw, not a generic line. Bytes that are not
  // an envelope decode as bare bytes under a generic reason.
  try {
    const envelope = JSON.parse(stored);
    if (
      isPlainObject(envelope) &&
      typeof envelope.raw === 'string' &&
      typeof envelope.reason === 'string'
    ) {
      return envelope;
    }
  } catch (_) {
    /* fall through: the bare-bytes form */
  }
  return { raw: stored, reason: 'unreadable bytes preserved by an earlier page load' };
}

function draftShapeProblem(parsed) {
  // Shape-first, permissive where age explains the difference (unknown extra
  // keys are left alone): every recognized key that IS present must hold the
  // type the accessors rely on, so a mirror the code would run on blindly is
  // named instead of trusted.
  if (!isPlainObject(parsed)) return 'the stored mirror is not a tick draft object';
  if (!('revision' in parsed) && !('ticks' in parsed)) {
    return 'the stored mirror has none of the draft keys';
  }
  if (parsed.revision !== undefined && parsed.revision !== null && typeof parsed.revision !== 'string') {
    return 'the mirror revision is not a string';
  }
  if (parsed.ticks !== undefined && !isPlainObject(parsed.ticks)) {
    return 'the mirror ticks is not an object';
  }
  if (isPlainObject(parsed.ticks) &&
      !Object.keys(parsed.ticks).every((id) => typeof parsed.ticks[id] === 'string')) {
    return 'the mirror ticks values are not strings';
  }
  return null;
}

export function createTickDrafts(storage) {
  // All state lives per instance: two tabs inject two storages and get two
  // drafts, never a merged one (Q1b: a second tab is its own draft).
  const tips = new Map(); // tipKey -> {revision, ticks: Map<taskId, wantedState>}
  const damaged = new Map(); // tipKey -> {raw, reason}: mirror bytes we could not read
  let persistent = true; // false from the first storage fault: memory only

  function mirrorKey(tipKey) {
    return encodeKey(TICK_PREFIX, tipKey);
  }

  function recoverKey(tipKey) {
    return encodeKey(CORRUPT_PREFIX, tipKey);
  }

  function snapshot(draft) {
    // A plain projection for readers and for the mirror. Null-prototype on
    // purpose: task ids are user data, and `__proto__` must be an ordinary
    // key, never a prototype setter tripped by a copy loop.
    const ticks = Object.create(null);
    for (const [taskId, state] of draft.ticks) ticks[taskId] = state;
    return { revision: draft.revision, ticks };
  }

  function reportDamage(tipKey, raw, reason) {
    // Bytes that existed but could not be read are evidence of unsaved
    // ticks, never a clean slate: keep them, report them, and let the draft
    // open clean so editing proceeds. If even the copy cannot be stored the
    // bytes live in this instance only; persistence is lost, silence never.
    damaged.set(tipKey, { raw, reason });
    try {
      storage.setItem(recoverKey(tipKey), JSON.stringify({ raw, reason }));
    } catch (_) {
      persistent = false;
    }
  }

  function read(tipKey) {
    let raw;
    let recovered;
    try {
      raw = storage.getItem(mirrorKey(tipKey));
      // a copy preserved by an earlier page load re-arms on every load, even
      // once a newer valid draft has taken the draft slot
      recovered = storage.getItem(recoverKey(tipKey));
    } catch (_) {
      persistent = false; // a blocked storage costs persistence, not editing
      return { revision: null, ticks: new Map() };
    }
    if (recovered) {
      const envelope = decodeEnvelope(recovered);
      reportDamage(tipKey, envelope.raw, envelope.reason);
    }
    if (raw === null || raw === undefined) return { revision: null, ticks: new Map() };
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      reportDamage(tipKey, raw, err.message);
      return { revision: null, ticks: new Map() };
    }
    const problem = draftShapeProblem(parsed);
    if (problem) {
      // parses but is not a tick draft: the same class of damage -- bytes,
      // not a draft -- reported, never silently loaded
      reportDamage(tipKey, raw, problem);
      return { revision: null, ticks: new Map() };
    }
    const ticks = new Map();
    const declared = parsed.ticks === undefined ? Object.create(null) : parsed.ticks;
    for (const taskId of Object.keys(declared)) ticks.set(taskId, declared[taskId]);
    return { revision: typeof parsed.revision === 'string' ? parsed.revision : null, ticks };
  }

  function draftFor(tipKey) {
    if (!tips.has(tipKey)) tips.set(tipKey, read(tipKey));
    return tips.get(tipKey);
  }

  function persist(tipKey, draft) {
    if (draft.ticks.size === 0) draft.revision = null; // an emptied draft has no stamp to carry
    if (!persistent) return; // storage judged broken: memory only
    try {
      // the mirror exists exactly while the draft has pending ticks; an
      // emptied draft leaves no key behind, so a reload sees the absence
      if (draft.ticks.size > 0) storage.setItem(mirrorKey(tipKey), JSON.stringify(snapshot(draft)));
      else storage.removeItem(mirrorKey(tipKey));
    } catch (_) {
      persistent = false; // a fault costs persistence, never the edit
    }
  }

  return {
    get(tipKey) {
      return snapshot(draftFor(tipKey));
    },
    setTick(tipKey, taskId, wantedState, originalState) {
      if (typeof taskId !== 'string') return false; // data, not code: never coerced
      const draft = draftFor(tipKey);
      if (wantedState === originalState) {
        // Q6b: the draft is not history -- a row returned to its original
        // state leaves no pending change, so the entry leaves the draft.
        if (!draft.ticks.delete(taskId)) return false;
      } else if (draft.ticks.get(taskId) === wantedState) {
        return false;
      } else {
        draft.ticks.set(taskId, wantedState);
      }
      persist(tipKey, draft);
      return true;
    },
    clearTick(tipKey, taskId) {
      if (typeof taskId !== 'string') return false;
      const draft = draftFor(tipKey);
      if (!draft.ticks.delete(taskId)) return false;
      persist(tipKey, draft);
      return true;
    },
    pendingCount(tipKey) {
      return draftFor(tipKey).ticks.size;
    },
    pendingTicks(tipKey) {
      // exactly the continue body's ticks list: [taskId, wantedState] pairs
      // in the order the author ticked (a cleared id re-ticked moves to the
      // end: Map set() appends an absent key)
      return [...draftFor(tipKey).ticks.entries()];
    },
    setRevision(tipKey, revision) {
      // the revision the pane rendered at rides the draft and the save posts
      // it; a draft with nothing pending has no opening to carry (the item
      // drafts' stamp rule), and the mirror must carry the stamp through a
      // reload, so a real change persists
      const draft = draftFor(tipKey);
      const stamp = draft.ticks.size > 0 ? revision || null : null;
      if (draft.revision === stamp) return;
      draft.revision = stamp;
      persist(tipKey, draft);
    },
    revision(tipKey) {
      return draftFor(tipKey).revision;
    },
    discard(tipKey) {
      // the explicit release (Q8a, the editor's rules): memory, the mirror
      // key, and the preserved bytes all go -- a draft that took over the
      // slot after the damage is the draft being discarded too, never
      // silently kept
      // memory goes to a clean draft, not out of the map: a later read must
      // not re-seed this tip from mirror bytes that failed to be removed
      tips.set(tipKey, { revision: null, ticks: new Map() });
      damaged.delete(tipKey);
      if (!persistent) return;
      try {
        storage.removeItem(mirrorKey(tipKey));
        storage.removeItem(recoverKey(tipKey));
      } catch (_) {
        persistent = false; // nothing to remove where we cannot write
      }
    },
    corrupt(tipKey) {
      const entry = damaged.get(tipKey);
      return entry ? { raw: entry.raw, reason: entry.reason } : null;
    },
    counts() {
      // the tab-switch UI's per-tip pending counts (Q5a); a tip whose draft
      // is empty is not listed
      const out = Object.create(null);
      for (const [tipKey, draft] of tips) {
        if (draft.ticks.size > 0) out[tipKey] = draft.ticks.size;
      }
      return out;
    },
    persistent() {
      // the non-DOM degradation channel: false from the first storage fault
      // (a blocked, private-mode, or full storage). Probing lazily keeps a
      // pure read of a working storage cheap.
      if (persistent) {
        try {
          storage.getItem(TICK_PREFIX);
        } catch (_) {
          persistent = false;
        }
      }
      return persistent;
    },
  };
}
