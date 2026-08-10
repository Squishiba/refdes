/* Hover/focus previews for cross-references.
 *
 * Everything is inlined at build time -- no network calls. Without JS the refs
 * remain ordinary working links, which is the whole point of doing this at build
 * time rather than fetching on demand.
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("preview-data");
  var card = document.getElementById("preview-card");
  if (!dataEl || !card) return;

  var previews;
  try {
    previews = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  var current = null;
  var hideTimer = null;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function build(p) {
    var state = "";
    if (p.check === "fail") {
      state = '<span class="pill pill-fail">check failing</span>';
    } else if (p.check === "pass") {
      state = '<span class="pill pill-pass">checks pass</span>';
    }
    var rows = p.fields
      .map(function (f) {
        return "<dt>" + esc(f.name) + "</dt><dd>" + esc(f.value) + "</dd>";
      })
      .join("");
    return (
      '<div class="pv-head"><span class="type-badge">' + esc(p.type) + "</span>" +
      '<span class="pv-id">' + esc(p.id) + "</span>" + state + "</div>" +
      '<div class="pv-title">' + esc(p.title) + "</div>" +
      (rows ? "<dl>" + rows + "</dl>" : "")
    );
  }

  function place(anchor) {
    var r = anchor.getBoundingClientRect();
    card.hidden = false;
    var cw = card.offsetWidth;
    var ch = card.offsetHeight;
    var left = window.scrollX + r.left;
    var top = window.scrollY + r.bottom + 8;

    // Keep the card on screen horizontally, and flip above when it would
    // otherwise run off the bottom of the viewport.
    var maxLeft = window.scrollX + document.documentElement.clientWidth - cw - 12;
    if (left > maxLeft) left = Math.max(window.scrollX + 12, maxLeft);
    if (r.bottom + ch + 16 > document.documentElement.clientHeight) {
      top = window.scrollY + r.top - ch - 8;
    }
    card.style.left = left + "px";
    card.style.top = top + "px";
  }

  function show(anchor) {
    var id = anchor.getAttribute("data-ref");
    var p = previews[id];
    if (!p) return;
    clearTimeout(hideTimer);
    card.innerHTML = build(p);
    current = anchor;
    place(anchor);
  }

  function hide() {
    card.hidden = true;
    current = null;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hide, 150);
  }

  function isRef(el) {
    return el && el.classList && el.classList.contains("ref") && el.hasAttribute("data-ref");
  }

  document.addEventListener("mouseover", function (e) {
    var a = e.target.closest ? e.target.closest("a.ref[data-ref]") : null;
    if (a) show(a);
  });

  document.addEventListener("mouseout", function (e) {
    var a = e.target.closest ? e.target.closest("a.ref[data-ref]") : null;
    if (a && a === current) scheduleHide();
  });

  card.addEventListener("mouseenter", function () {
    clearTimeout(hideTimer);
  });
  card.addEventListener("mouseleave", scheduleHide);

  // Keyboard: previews follow focus, Escape dismisses.
  document.addEventListener("focusin", function (e) {
    if (isRef(e.target)) show(e.target);
  });
  document.addEventListener("focusout", function (e) {
    if (e.target === current) scheduleHide();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !card.hidden) {
      hide();
      if (current && current.blur) current.blur();
    }
  });

  // Touch: hover does not exist, so the first tap opens the preview and the
  // second follows the link.
  var touched = null;
  document.addEventListener(
    "touchstart",
    function (e) {
      var a = e.target.closest ? e.target.closest("a.ref[data-ref]") : null;
      if (!a) {
        hide();
        touched = null;
        return;
      }
      if (touched !== a) {
        e.preventDefault();
        touched = a;
        show(a);
      }
    },
    { passive: false }
  );

  window.addEventListener("scroll", function () {
    if (current) place(current);
  }, { passive: true });
})();
