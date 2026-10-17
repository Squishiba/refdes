# refdes-worker-permissions

Server-only Paseo plugin that stops Sol-dispatched Qwen refdes fix workers
from blocking on repeated `external_directory` approval prompts, by
auto-answering **only** the two narrowest routine request shapes. It is a
replacement for the (unsafe) idea of a broad `external_directory` allow in
`opencode.json`: project config cannot distinguish read from write for bash
(`edit: deny` does not constrain shell redirections or Python writes), so the
allowlist lives in a permission hook that inspects each request.

**Not deployed.** Nothing here is installed on any daemon; see
[Presentation](#presentation) for the exact review/install path.

## Policy (fail-closed)

`index.server.ts` subscribes to `agent.permission_requested`
(https://paseo.sh/docs/plugins/reference.md, "Answer a permission request")
and answers a request **only** when every gate in
`shared/classifier.ts` passes; everything else is left pending for a human.

| Gate | Requirement |
| --- | --- |
| Agent | `agent.provider === "opencode"` and `agent.parentAgentId === "d86b9967-5a0c-41e5-8635-fca6170fdeaa"` (Sol's dispatcher) |
| Request | `request.provider === "opencode"`, `request.kind === "tool"`, `request.name === "external_directory"` |
| Case 1: exact progress file | a metadata `filepath`/`file`/`path` string (at `request.input.metadata` or its nested `input`) equal **exactly** to `/home/jorb/work/refdes/.scratch/PROGRESS.md` — no globs, no prefixes |
| Case 2: read-only evidence command | command text (at `request.input.command` or metadata `command`/`cmd`/`shellCommand`, incl. nested `input`) is a single command whose characters are restricted to `[A-Za-z0-9 ./_\-,:=%+@]` (no `;` `|` `&` `>` `<` `` ` `` `$` `(` `)` `{` `}` `[` `]` `*` `?` `!` quotes, backslash, newline), whose program is exactly `cat`, `head`, or `rg`, whose flags are on a per-program allowlist (rejecting `rg --pre`, `-f`, `--hostname-bin`, `--config`, ...), and whose path arguments all resolve (no `..` segments) under `/home/jorb/work/refdes/in-prog-logs/` (root itself included) or name the exact progress file. `rg` requires an explicit path argument, and a pattern positional |

Never auto-approved: any other parent agent, provider, permission name, kind
(questions, plans, mode changes), arbitrary directory scopes (e.g.
`.../.scratch/*`), writes to source, commands with shell operators,
redirections, substitutions, quoting, environment/exec wrappers, unlisted
flags. Never auto-denied either — a human always keeps control of the
remainder.

## Payload sufficiency (why exact file paths are enforceable)

The daemon's OpenCode adapter
(`@getpaseo/server .../providers/opencode-agent.js`, verified 2026-10-15 in
the running 0.11.2 daemon) builds each OpenCode `permission.asked` event into
`AgentPermissionRequest` with `name = <permission>` (e.g.
`external_directory`), `kind: "tool"`, and `input = { patterns, metadata,
tool, command }` — passing OpenCode's raw `metadata` (which carries the tool's
`filepath` for file tools) and the parsed command text through. Hook events
also carry `agent.parentAgentId`
(`PluginHookAgent`, documented). That is enough for both cases; the
classifier fails closed (stays pending) if a payload shape ever lacks them.

## Tests

```sh
cd tools/paseo-worker-permissions
npm install
npm run typecheck   # tsc --noEmit against @getpaseo/plugin 0.11.2
npm test            # node --test, 17 tests
```

Positive cases: exact progress-file read/edit, `cat`/`head`/`rg` over
`in-prog-logs`, numeric flags, `-e` patterns, progress file as a path
argument, nested `metadata.input` command. Negative cases: null/foreign
parent, other providers/permissions/kinds, missing metadata, non-progress
filepaths, glob filepaths, redirections/pipes/chaining/`$()`/backticks/
newlines/`&`, quoting, `bash -c`/`env` wrappers, exec-capable `rg` flags,
`--help`, negative `head -n -5`, paths outside evidence roots incl. `..`
traversal, no-path invocations.

## Presentation (install only after review — deliberately not done here)

```sh
paseo plugin install /home/jorb/.paseo/worktrees/16msma8v/fix-worker-permission-policy-20261015/tools/paseo-worker-permissions
paseo plugin ls          # require status running, no error
paseo plugin reload refdes-worker-permissions
paseo plugin logs refdes-worker-permissions
paseo plugin remove refdes-worker-permissions   # rollback
```

Config changes to the daemon-wide plugin switch (`pluginsEnabled`) require a
human (Settings -> Plugins) and `paseo reload`; source edits need only
`paseo plugin reload`. Do not restart the daemon. Auto-allow takes effect for
agents spawned after the install; existing sessions resume on their next
request.

## Known limits

- `respondToPermission` on an already-answered request fails; the plugin
  logs and moves on (human wins the race — safe).
- The classifier never inspects bash contents for *reads inside the
  worktree* (not needed — those never trigger `external_directory`).
- Sol's dispatcher id is hard-coded by design (narrowest scope); a Sol
  restart that changes the id requires a one-line policy edit.
