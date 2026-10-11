/* The floating task pane (docs/design/thread-workbench.md §7a, W5a).

   Progressive enhancement: every byte the pane shows was rendered by
   Python from `threads.threads_projection` — the same projection
   `refdes thread` prints. This file computes nothing: it shows and hides,
   switches tabs, and greys the pane when no thread is in view. It fetches
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
    open = next;
    panes.forEach(function (pane) {
      pane.hidden = !(open && pane === current);
    });
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

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
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (other) {
          var selected = other === tab;
          other.setAttribute("aria-selected", selected ? "true" : "false");
          other.tabIndex = selected ? 0 : -1;
        });
        panels.forEach(function (panel) {
          panel.hidden =
            panel.getAttribute("data-refdes-panel") !==
            tab.getAttribute("data-refdes-tab");
        });
      });
    });
  });

  // §7a sub-decision 2: the pane follows the thread that is in view. Every
  // anchor carrying `data-refdes-thread` names the thread of the content
  // under it; an item page has exactly one, which is why the pane's thread
  // is simply the page's item's thread today. §7a sub-decision 5: with
  // none in view the pane stays put, greyed, still naming the last thread.
  var anchors = Array.prototype.slice.call(
    document.querySelectorAll("[data-refdes-thread]")
  );
  if (!("IntersectionObserver" in window) || !anchors.length) return;

  var visible = {};
  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        var ref = entry.target.getAttribute("data-refdes-thread");
        if (entry.isIntersecting) {
          visible[ref] = true;
        } else {
          delete visible[ref];
        }
      });
      for (var i = 0; i < anchors.length; i++) {
        var ref = anchors[i].getAttribute("data-refdes-thread");
        if (visible[ref]) {
          var pane = paneFor(ref);
          if (pane) {
            panes.forEach(function (other) {
              other.classList.remove("refdes-taskpane-grey");
            });
            if (pane !== current) {
              current = pane;
              if (open) setOpen(true);
            }
          }
          return;
        }
      }
      panes.forEach(function (other) {
        other.classList.add("refdes-taskpane-grey");
      });
    },
    { rootMargin: "0px 0px -20% 0px", threshold: 0 }
  );
  anchors.forEach(function (anchor) {
    observer.observe(anchor);
  });
})();
