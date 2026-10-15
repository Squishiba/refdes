/* The floating task pane (docs/design/thread-workbench.md §7a, W5a).

   Progressive enhancement: every byte the pane shows was rendered by
   Python from `threads.threads_projection` — the same projection
   `refdes thread` prints. This file computes nothing: it shows and hides,
   switches tabs, and — only on a page carrying more than one thread
   anchor — greys the pane when no thread is in view (today's item pages
   carry one anchor, so their pane never greys; see §7a's W5a status note
   in docs/design/thread-workbench.md). It fetches
   nothing and writes nothing; with JavaScript disabled the pane never
   appears and the page reads fully. The file itself ships only for
   projects that show a pane (render.py emits it per project, the same way
   theme.css is generated). */
(function () {
  "use strict";

  var toggle = document.getElementById("refdes-taskpane-toggle");
  var panes = Array.prototype.slice.call(
    document.querySelectorAll(".refdes-taskpane")
  );
  if (!toggle || !panes.length) return;

  var open = false;
  var current = panes[0];

  function paneFor(ref) {
    for (var i = 0; i < panes.length; i++) {
      if (panes[i].getAttribute("data-refdes-taskpane") === ref) {
        return panes[i];
      }
    }
    return null;
  }

  function setOpen(next) {
    // K5: focus returns to the toggle only when it was actually inside a
    // pane — Escape with focus elsewhere on the page must not move it. The
    // read has to happen BEFORE the panes are hidden, or the focus check
    // sees the element already gone from the layout.
    var focusWasInside = panes.some(function (pane) {
      return pane.contains(document.activeElement);
    });
    open = next;
    panes.forEach(function (pane) {
      pane.hidden = !(open && pane === current);
    });
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (!next && focusWasInside) {
      // The pane just took the focus with it as it hid: hand it back to the
      // one control that can open it again (PR #197 review C3, narrowed by
      // K5). Presentation-only, like everything here.
      toggle.focus();
    }
  }

  // Escape closes the pane (PR #197 review C3). It closes only what is open
  // and computes nothing — with the pane closed the key does nothing at all.
  // K5: a keydown another handler already claimed (defaultPrevented) is not
  // ours to act on. Round-6: nor is one pressed somewhere else on the page —
  // app.js dismisses its hover preview card on the same key WITHOUT calling
  // preventDefault (templates/assets/app.js ~122), so a blanket document
  // handler closed both surfaces on a single press. We act only when the key
  // lands on us: focus inside the pane or on the toggle, or focus nowhere at
  // all (body/documentElement), where no other handler owns the press.
  document.addEventListener("keydown", function (event) {
    if (event.defaultPrevented) return;
    if (!open || event.key !== "Escape") return;
    var target = event.target;
    var ours =
      target === toggle ||
      panes.some(function (pane) {
        return pane.contains(target);
      });
    var unowned =
      target === document.body || target === document.documentElement;
    if (ours || unowned) {
      setOpen(false);
    }
  });

  // The toggle is marked `hidden` in the page so a reader with JavaScript
  // off never sees a dead control; revealing it is the first thing the
  // script does.
  toggle.hidden = false;
  toggle.addEventListener("click", function () {
    setOpen(!open);
  });

  panes.forEach(function (pane) {
    var close = pane.querySelector(".refdes-taskpane-close");
    if (close) {
      close.addEventListener("click", function () {
        setOpen(false);
      });
    }
    var tabs = Array.prototype.slice.call(
      pane.querySelectorAll("[data-refdes-tab]")
    );
    var panels = Array.prototype.slice.call(
      pane.querySelectorAll("[data-refdes-panel]")
    );
    // §7a sub-decision 3: a fork shows one tab per open tip. Switching a
    // tab only moves which pre-rendered panel is visible — no task list is
    // ever assembled here.
    function selectTab(tab) {
      tabs.forEach(function (other) {
        var selected = other === tab;
        other.setAttribute("aria-selected", selected ? "true" : "false");
        // Roving tabindex: the selected tab is the only stop in the
        // tablist; the arrow keys move the stop with the selection.
        other.tabIndex = selected ? 0 : -1;
      });
      panels.forEach(function (panel) {
        panel.hidden =
          panel.getAttribute("data-refdes-panel") !==
          tab.getAttribute("data-refdes-tab");
      });
    }
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        selectTab(tab);
      });
      // The standard ARIA tabs keyboard pattern (PR #197 review B3):
      // Left/Right move selection AND focus, wrapping at the ends; Home/End
      // jump. Presentation-only, like everything here — it switches which
      // pre-rendered panel is visible and computes no task state.
      tab.addEventListener("keydown", function (event) {
        // Round-6: a press another handler already claimed, and a chord
        // (Ctrl/Meta/Alt + arrow is a browser or page shortcut), are not
        // ours to swallow — only the bare arrow/Home/End keys are.
        if (event.defaultPrevented) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        var at = tabs.indexOf(tab);
        var next = null;
        if (event.key === "ArrowLeft") {
          next = tabs[(at - 1 + tabs.length) % tabs.length];
        } else if (event.key === "ArrowRight") {
          next = tabs[(at + 1) % tabs.length];
        } else if (event.key === "Home") {
          next = tabs[0];
        } else if (event.key === "End") {
          next = tabs[tabs.length - 1];
        }
        if (next === null) return;
        event.preventDefault();
        selectTab(next);
        next.focus();
      });
    });
  });

  // §7a sub-decision 2: the pane follows the thread that is in view. Every
  // anchor carrying `data-refdes-thread` names the thread of the content
  // under it. This only ACTS when a page carries MORE THAN ONE thread
  // anchor: today's item pages carry exactly one (the whole
  // `<article class="item">`, item.html.j2), which is always in view, so
  // the switching/greying below can never fire on them — hence K3's skip:
  // with at most one anchor the observer is not set up at all and the pane
  // never greys. It matters once a page shows several entries; §7a
  // sub-decision 5 (none in view → greyed, still naming the last thread)
  // is that future multi-anchor shape's rule.
  var anchors = Array.prototype.slice.call(
    document.querySelectorAll("[data-refdes-thread]")
  );
  if (anchors.length < 2) return;
  if (!("IntersectionObserver" in window)) return;

  // Round-6: visible anchors are tracked BY ELEMENT. Keyed by the `ref` they
  // name, two anchors of the same thread cancelled each other — one leaving
  // the viewport deleted the other's entry, so a thread still on screen
  // read as not-in-view.
  var visible = [];
  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        var at = visible.indexOf(entry.target);
        if (entry.isIntersecting) {
          if (at === -1) visible.push(entry.target);
        } else if (at !== -1) {
          visible.splice(at, 1);
        }
      });
      for (var i = 0; i < anchors.length; i++) {
        if (visible.indexOf(anchors[i]) === -1) continue;
        // Something is in view, so no pane is greyed — and that includes the
        // case where the anchor in view names a thread with no pane of its
        // own (round-6: the old code returned before un-greying, leaving the
        // panes greyed while a thread was plainly on screen).
        panes.forEach(function (other) {
          other.classList.remove("refdes-taskpane-grey");
          other.removeAttribute("aria-disabled");
        });
        var pane = paneFor(anchors[i].getAttribute("data-refdes-thread"));
        if (pane && pane !== current) {
          current = pane;
          if (open) setOpen(true);
        }
        return;
      }
      panes.forEach(function (other) {
        other.classList.add("refdes-taskpane-grey");
        // K3: the greyed pane is not dead keys, only greyed paint; say so
        // to assistive tech without hiding it from the page.
        other.setAttribute("aria-disabled", "true");
      });
    },
    { rootMargin: "0px 0px -20% 0px", threshold: 0 }
  );
  anchors.forEach(function (anchor) {
    observer.observe(anchor);
  });
})();
