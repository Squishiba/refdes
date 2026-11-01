# refdes-worker-permissions

Server-only Paseo plugin that stops refdes fix workers from blocking on
repeated `external_directory` approval prompts, by auto-answering **only**
requests whose released scope is provably inside a small allowlist of
directory roots. It replaces the (unsafe) idea of a broad
`external_directory` allow in `opencode.json`: project config cannot
distinguish read from write for bash (`edit: deny` does not constrain shell
redirections or Python writes), so the allowlist lives in a permission hook
that inspects each request.

**Not deployed.** Nothing here is installed on any daemon; see
[Presentation](#presentation-human-only) for the exact review/install path.
Installing is a **human act**.

## Policy (fail-closed)

`index.server.ts` subscribes to `agent.permission_requested`
(https://paseo.sh/docs/plugins/reference.md, "Answer a permission request")
and answers a request **only** when every gate in `shared/classifier.ts`
passes; everything else is left pending for a human. Nothing is auto-denied.

| Gate | Requirement |
| --- | --- |
| Provider/request | `agent.provider === "opencode"`, `request.provider === "opencode"`, `request.kind === "tool"`, `request.name === "external_directory"` |
| Identity | `agent.parentAgentId` is on the dispatcher allowlist loaded from `parents.json` (below; absent/invalid file = empty list = nothing approved), **or** `agent.title` starts with `"Review PR "` (the PR-review plugin's reviewer agents) |
| Scope | `request.input.patterns` is a **non-empty array of strings** and **every** entry passes: absolute, no `..` segment, no glob metacharacter other than `*` (the downstream matcher expands `[..]`, `{..,..}`, `?`, `!`, `(`, `)`, and backslash escapes, so those plus `$`, quotes, and `;` are rejected), and `*` is allowed **only as the exact final path segment** (`<dir>/*`; `**`, a mid-path `*`, and `a*b` are rejected). It sits inside one of the roots below at a path-segment boundary (the root itself, or `root + "/..."`); the literal prefix is realpath'd and the deepest existing ancestor must resolve inside the realpath'd roots. For a `<dir>/*` pattern the **direct children** of `<dir>` are enumerated at decision time: a child symlink whose real target lies outside the roots rejects the request, a directory with more than 5000 entries is rejected, and any fs error is rejected (missing dir = no children = passes). All patterns must pass; one bad entry rejects the whole request |

Allowed roots (hard-coded in `shared/classifier.ts`):

- `/home/jorb/.paseo/worktrees/16msma8v` — the **whole** worktrees directory
  of this project: an approved worker can read/write any sibling worktree
  under it, not just its own. This is the accepted design (2026-10-18);
  per-worktree isolation was explicitly not required.
- `/home/jorb/work/refdes` — the refdes checkout
- `/home/jorb/work/venv-refdes` — the project venv

Everything else fails closed, including: patterns with `..`, glob
metacharacters other than `*` (`[.][.]/etc/passwd`, `{..,x}/y`), wildcards
in any shape other than a final `*` (`**`, `/src*/x`, `a*b`), root-prefix
lookalikes (`/home/jorb/work/refdes-evil`), relative patterns, `/home/jorb/.paseo/*`
and `/home/jorb/.paseo/worktrees/*` (other projects, daemon config),
missing/empty `patterns`, non-string entries, any other provider, permission
name, or kind (questions, plans, mode changes).

The scope check is the whole policy: metadata `filepath` and bash command
text are **not** approval keys. The old metadata-keyed cases from the first
revision are retired (the 2026-10-17 security review showed they approved
scopes the classifier never read — see [Why scope](#why-scope-not-metadata)).
A `cat`/`head`/`rg` evidence command is approved only through its patterns,
same as everything else; writes inside the roots are in scope by design.

## Config: parents.json (dispatcher allowlist)

`index.server.ts` reads, on every request:

```
~/.paseo/plugin-settings/refdes-worker-permissions/parents.json
```

(the daemon's `plugin-settings/<plugin-id>` convention; override the whole
path with the env var `REFDES_WORKER_PERMISSIONS_PARENTS_FILE`, or the
`.paseo` home with `PASEO_HOME`; an **empty-string** value of either is
treated as unset). Format:

```json
{
  "parentAgentIds": [
    "f3993852-557c-4a4e-989b-6490584ef5c8",
    "d86b9967-5a0c-41e5-8635-fca6170fdeaa"
  ]
}
```

`parents.example.json` in this directory is a ready copy. First id: Claude,
the current dispatching orchestrator (primary). Second: Sol, backup.
**Absent, unparseable, or schema-violating file = empty allowlist = nothing
approved** (reviewer agents by title are unaffected).

## Why scope, not metadata

The 2026-10-17 security review found the first revision decided on request
*metadata* (exact `filepath`, safe-looking command text) while ignoring
`request.input.patterns` — the scope OpenCode actually releases on allow.
A metadata filepath equal to the shared PROGRESS.md file could therefore
approve a wildcard directory request such as `.scratch/*`.

Verified against the **installed** daemon's OpenCode adapter
(`@getpaseo/cli/node_modules/@getpaseo/server/dist/server/server/agent/
providers/opencode-agent.js`, `appendOpenCodePermissionAsked` /
`buildOpenCodePermissionInput`, checked 2026-10-18 against 0.11.2):
OpenCode `permission.asked` maps to `request.input = {patterns, metadata,
tool, command}` — `patterns` (string-filtered from the event) is the granted
scope; `patterns` is **omitted** when the event carries none. The hook agent
payload (`server/plugins/lifecycle/index.js`) carries `id`,
`workspaceId`, `parentAgentId`, `provider`, `cwd` **and `title`** — so the
`"Review PR "` reviewer match uses a real, documented field, not a guess.
Any missing/unexpected payload shape fails closed to pending.

## Tests

Node **22.18 or newer** is required: native TypeScript type-stripping for
`node --test` is flag-free only from 22.18 (below that `npm test` fails with
`Unknown file extension ".ts"`); `package.json` declares `engines`.

```sh
cd tools/paseo-worker-permissions
npm install
npm run typecheck   # tsc --noEmit against @getpaseo/plugin 0.11.2
npm test            # node --test, 25 tests
```

The suite is red on the pre-fix classifier. Key cases: wildcard
`.scratch/*` with an exact-progress-file metadata path → **not** approved;
scope decided by patterns, not metadata; positives (worktree subpath,
checkout subpath, venv bin, exact roots); `..` segments, lookalike roots,
`/home/jorb/.paseo/*` and `.../worktrees/*`, outside-root paths,
mixed allowed+disallowed, missing/empty/non-string/blank patterns → pending;
every glob metacharacter other than `*` (incl. the `[.][.]/etc/passwd`,
`{..,x}/y`, `..\/etc`, `$HOME/x` probes) → pending; wildcards outside the
final-segment form (`**`, mid-path `*`, `a*b`) → pending, while `<dir>/*`
is checked for escaping child symlinks (fake resolvers: clear → allow,
escape/too-many/throw → pending; a real `fs` resolver test against a temp
dir with a real `link -> /etc` symlink in `./.scratch/`); plain
non-wildcard patterns unchanged under the identity default (wildcards
pending there); `policy.roots` flips decisions both ways; foreign/null
parent → pending; empty allowlist (config absent) → nothing; Claude+Sol
both accepted; reviewer title-prefix matching incl. near-miss titles;
command text alone approves nothing.

## Presentation (human only)

```sh
paseo plugin install <path-to-repo>/tools/paseo-worker-permissions
paseo plugin ls          # require status running, no error
paseo plugin reload refdes-worker-permissions
paseo plugin logs refdes-worker-permissions
paseo plugin remove refdes-worker-permissions   # rollback
```

Create `parents.json` (above) before enabling. Config changes to the
daemon-wide plugin switch (`pluginsEnabled`) require a human (Settings ->
Plugins) and `paseo reload`; source edits need only `paseo plugin reload`.
Do not restart the daemon. Auto-allow takes effect for agents spawned after
the install; existing sessions resume on their next request.

## Known limits

- Writes inside the allowed roots (incl. the main checkout) are approved by
  design — the root allowlist is the security boundary, replacing the first
  revision's narrower metadata cases at Jared's direction (2026-10-17).
  The first root is the project's whole worktrees directory, so an approved
  worker can write into any sibling worktree under it; accepted design
  (2026-10-18).
- A wildcard is allowed **only as a final `*`** (`<dir>/*`); `**`, a
  mid-path `*`, and `a*b` are never approved. For `<dir>/*` the direct
  children of `<dir>` are listed at decision time and a child symlink whose
  real target lies outside the roots rejects the request; directories with
  more than 5000 entries are rejected (pending), as is any fs error during
  the listing (a missing directory has no children and passes).
- Symlinks are resolved **at check time**. A symlink (or directory) created
  or swapped to point outside a root *after* the check, before the tool
  actually opens the path, is a check/use race the plugin cannot close; the
  roots are local, human-owned directories. The daemon matcher's own
  semantics for `*` (dot entries, ordering) are not verified by this
  plugin — only the direct-children listing is.
- The default `PathResolver` is the identity (lexical checks only) when a
  caller omits it, and it cannot answer wildcard child inspections — so
  wildcard patterns stay **pending** under the default; `index.server.ts`
  always passes the fs-backed resolver. The identity default is for unit
  tests, not deployment.
- A missing or unparseable `parents.json` approves **nothing, silently**
  (fail closed, no warning at install). The
  `REFDES_WORKER_PERMISSIONS_PARENTS_FILE` / `PASEO_HOME` environment
  overrides are an extra trust input: whoever controls the daemon's
  environment controls the allowlist path.
- Dispatcher ids live in `parents.json`; a rotation is a file edit, no code
  change, no reinstall.
- The `"Review PR "` title prefix is an accepted identity key: **any**
  opencode agent whose title starts with it is approved for in-root
  patterns. Accepted because titles are set by the orchestrators/humans who
  are already trusted to run agents over exactly these roots, the gate adds
  no scope (scope stays root-checked), and the reviewer plugin's agents
  cannot be created by the workers the plugin serves.
- `respondToPermission` on an already-answered request fails; the plugin
  logs and moves on (human wins the race — safe).
- Relative patterns are rejected (fail-closed); observed OpenCode
  `external_directory` events carry absolute globs.
- The classifier never inspects bash contents; a safe command text grants
  nothing by itself, and an approved bash request releases only its
  in-root patterns.
