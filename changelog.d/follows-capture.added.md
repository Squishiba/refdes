A writable load that freezes a `follows:` edge now also captures the
predecessor's snapshot into `.refdes/history/` as a `followed` event and
announces it on stderr: `captured LOG-A-011: LOG-A-012 now follows it`.
Re-pointing a frozen edge at a different predecessor on a later save adds a
`followed-corrected` event naming the superseded key; the original event is
never deleted or rewritten. Re-running the same load writes nothing new, an
old-branch replay regenerates the identical event path and bytes, and
`--no-write` writes nothing anywhere under `.refdes/history/`. If an event
write fails, the frozen edges roll back to their authored text so no edge
is ever frozen without its event. (Living notes phase H2.)
