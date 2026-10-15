- The browser editor no longer silently discards an unreadable draft
  mirror. The sessionStorage mirror of unsaved work that survives a tab
  reload can be truncated, mangled, or shaped like something that is not
  a draft (an object with the draft's keys missing, a list, a bare
  value). The editor used to catch that in the same clause as a
  private-mode storage failure and open a clean form: status "saved",
  no close prompt, no message -- unsaved work indistinguishable from no
  work, and a tab close quietly destroyed the evidence. Now the
  unreadable bytes are preserved in sessionStorage under
  `refdes.draft.corrupt.v1.<handle>` (copy them out of DevTools to
  recover what you can), the parse reason is named in the console and
  kept across reloads, a visible banner on the page names the recovery
  key, and the close prompt stays armed while the mirror is preserved.
  Recovery stays discoverable on every reload -- even after new edits
  have replaced the mirror slot -- until you press Discard on the
  banner, which clears it durably and never deletes a newer draft.
  Editing always proceeds from the live item; blocked storage (private
  mode, quota) keeps its documented silent behavior: there is nothing
  there to read *or* preserve.
