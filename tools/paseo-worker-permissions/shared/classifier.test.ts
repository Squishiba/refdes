import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync, symlinkSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  classifyWorkerPermissionRequest,
  WORKER_PERMISSION_POLICY,
  type ClassifierAgent,
  type ClassifierRequest,
  type PathResolver,
  type WorkerPermissionPolicy,
} from "./classifier.ts";
import { createFsResolver } from "../fs-resolver.ts";

const CLAUDE = "f3993852-557c-4a4e-989b-6490584ef5c8";
const SOL = "d86b9967-5a0c-41e5-8635-fca6170fdeaa";
const PROGRESS = "/home/jorb/work/refdes/.scratch/PROGRESS.md";
const WORKTREE_ROOT = "/home/jorb/.paseo/worktrees/16msma8v";

const POLICY: WorkerPermissionPolicy = { ...WORKER_PERMISSION_POLICY, parentAgentIds: [CLAUDE, SOL] };

/** Identity resolver whose inspected directories always report "clear". */
const CLEAR: PathResolver = { realpath: (p) => p, childSymlinkEscapes: () => "clear" };

function agent(
  over: Partial<Pick<ClassifierAgent, "provider" | "parentAgentId" | "title">> = {},
): ClassifierAgent {
  return {
    provider: "opencode",
    parentAgentId: CLAUDE,
    title: null,
    ...over,
  };
}

function externalDirectory(input: Record<string, unknown> | undefined): ClassifierRequest {
  return { provider: "opencode", name: "external_directory", kind: "tool", input };
}

function allow(input: Record<string, unknown> | undefined, a = agent()) {
  return classifyWorkerPermissionRequest(a, externalDirectory(input), POLICY, CLEAR);
}

// ---------------------------------------------------------------------------
// Headline security test (the 2026-10-17 review finding, verbatim):
// a metadata filepath equal to the exact progress file must NOT approve a
// wildcard directory request — the scope is patterns, not metadata.
// ---------------------------------------------------------------------------

test("wildcard .scratch/* with exact progress-file metadata is NOT approved", () => {
  const input = { patterns: [".scratch/*"], metadata: { filepath: PROGRESS } };
  assert.equal(allow(input).action, "pending");
  assert.equal(allow(input, agent({ parentAgentId: SOL })).action, "pending");
});

test("absolute patterns decide the scope, not metadata.filepath", () => {
  const granted = allow({
    patterns: ["/home/jorb/work/refdes/.scratch/*"],
    metadata: { filepath: PROGRESS },
  });
  assert.equal(granted.action, "allow");
  const overgrant = allow({
    patterns: ["/home/jorb/.paseo/worktrees/16msma8v/feat-x/.scratch/*"],
    metadata: { filepath: PROGRESS },
  });
  assert.equal(overgrant.action, "allow");
});

// ---------------------------------------------------------------------------
// Scope gate: patterns must be a non-empty string array, absolute, no ..,
// every entry inside an allowlisted root at a path-segment boundary.
// ---------------------------------------------------------------------------

test("positives: worktree subpath, checkout subpath, venv bin, exact roots", () => {
  for (const patterns of [
    [`${WORKTREE_ROOT}/feat-x/src/refdes/model.py`],
    [`${WORKTREE_ROOT}/feat-x/in-prog-logs/*`],
    [WORKTREE_ROOT],
    ["/home/jorb/work/refdes/in-prog-logs/worker-permission-policy-20261015.txt"],
    ["/home/jorb/work/refdes/src/refdes/*"],
    ["/home/jorb/work/venv-refdes/bin"],
    ["/home/jorb/work/venv-refdes"],
  ]) {
    const decision = allow({ patterns });
    assert.equal(decision.action, "allow", `expected allow for ${patterns.join(",")}`);
  }
});

test("rejects patterns with .. segments", () => {
  for (const patterns of [
    ["/home/jorb/work/refdes/../.ssh/*"],
    ["/home/jorb/work/refdes/.scratch/../.git/config"],
    [`${WORKTREE_ROOT}/../../home/jorb/.paseo/config.json`],
  ]) {
    const decision = allow({ patterns });
    assert.equal(decision.action, "pending", `expected pending for ${patterns.join(",")}`);
  }
});

test("rejects root-prefix lookalikes", () => {
  for (const patterns of [
    ["/home/jorb/work/refdes-evil"],
    ["/home/jorb/work/refdes-evil/src/*"],
    [`${WORKTREE_ROOT}-evil/x`],
    ["/home/jorb/work/venv-refdes-old/bin/python"],
  ]) {
    const decision = allow({ patterns });
    assert.equal(decision.action, "pending", `expected pending for ${patterns.join(",")}`);
  }
});

test("rejects .paseo scopes outside this project's worktrees", () => {
  for (const patterns of [
    ["/home/jorb/.paseo/*"],
    ["/home/jorb/.paseo/worktrees/*"],
    ["/home/jorb/.paseo/worktrees/other-project/x"],
    ["/home/jorb/.paseo/worktrees"],
    ["/home/jorb/.paseo/config.json"],
    ["/home/jorb/.paseo/plugins/x"],
  ]) {
    const decision = allow({ patterns });
    assert.equal(decision.action, "pending", `expected pending for ${patterns.join(",")}`);
  }
});

test("rejects anything outside the roots", () => {
  for (const patterns of [
    ["/home/jorb/.ssh/*"],
    ["/home/jorb/work/other-repo/x"],
    ["/etc/*"],
    ["/"],
    ["/home/jorb"],
    ["relative/path/*"],
    ["src/refdes/model.py"],
    ["~/.ssh/*"],
    ["/home/jorb/work/refdes/../refdes-evil/*"],
  ]) {
    const decision = allow({ patterns });
    assert.equal(decision.action, "pending", `expected pending for ${patterns.join(",")}`);
  }
});

test("mixed allowed+disallowed patterns are rejected as a whole", () => {
  const decision = allow({
    patterns: ["/home/jorb/work/refdes/in-prog-logs/x", "/home/jorb/.ssh/id_ed25519"],
  });
  assert.equal(decision.action, "pending");
});

test("policy.roots (not hard-coded defaults) decide: flips both ways", () => {
  const custom: WorkerPermissionPolicy = {
    ...POLICY,
    roots: ["/srv/other", "/home/jorb/work/venv-refdes/bin"],
  };
  const classify = (patterns: string[], p: WorkerPermissionPolicy) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), p).action;
  const inDefault = ["/home/jorb/work/refdes/in-prog-logs/x"];
  const inCustom = ["/home/jorb/work/venv-refdes/bin", "/srv/other/x"];
  assert.equal(classify(inDefault, POLICY), "allow");
  assert.equal(classify(inDefault, custom), "pending");
  assert.equal(classify(inCustom, custom), "allow");
  assert.equal(classify(inCustom, POLICY), "pending");
});

test("missing, empty, non-string, blank patterns fail closed", () => {
  const cases: Array<Record<string, unknown> | undefined> = [
    undefined,
    {},
    { patterns: [] },
    { patterns: "/home/jorb/work/refdes/*" },
    { patterns: [42] },
    { patterns: [null] },
    { patterns: [""] },
    { patterns: ["/home/jorb/work/refdes/x", ""] },
    { patterns: [{}] },
  ];
  for (const input of cases) {
    const decision = allow(input);
    assert.equal(decision.action, "pending", `expected pending for ${JSON.stringify(input)}`);
  }
});

// ---------------------------------------------------------------------------
// Identity gate: parent allowlist comes from policy config (file-backed);
// reviewer agents of the PR-review plugin match by title prefix.
// ---------------------------------------------------------------------------

test("foreign, null and undefined parents are never approved", () => {
  const inputs = [{ patterns: ["/home/jorb/work/refdes/*"] }];
  for (const a of [
    agent({ parentAgentId: "11111111-2222-3333-4444-555555555555" }),
    agent({ parentAgentId: null }),
    { provider: "opencode", title: null } as ClassifierAgent,
  ]) {
    for (const input of inputs) {
      assert.equal(classifyWorkerPermissionRequest(a, externalDirectory(input), POLICY).action, "pending");
    }
  }
});

test("empty parent allowlist (config absent) approves nothing, even for Sol/Claude", () => {
  const empty: WorkerPermissionPolicy = { ...WORKER_PERMISSION_POLICY, parentAgentIds: [] };
  for (const parentAgentId of [CLAUDE, SOL]) {
    const decision = classifyWorkerPermissionRequest(
      agent({ parentAgentId }),
      externalDirectory({ patterns: ["/home/jorb/work/refdes/*"] }),
      empty,
    );
    assert.equal(decision.action, "pending");
  }
});

test("both allowlisted parents (Claude primary, Sol backup) are accepted", () => {
  for (const parentAgentId of [CLAUDE, SOL]) {
    const decision = classifyWorkerPermissionRequest(
      agent({ parentAgentId }),
      externalDirectory({ patterns: ["/home/jorb/work/refdes/*"] }),
      POLICY,
      CLEAR,
    );
    assert.equal(decision.action, "allow");
  }
});

test("reviewer agents match by title prefix 'Review PR '", () => {
  const reviewer = agent({ parentAgentId: null, title: "Review PR #269 (chunk 1/2)" });
  assert.equal(
    classifyWorkerPermissionRequest(reviewer, externalDirectory({ patterns: ["/home/jorb/work/refdes/*"] }), POLICY, CLEAR)
      .action,
    "allow",
  );
  for (const title of ["Review PR", "Reviews PR 1", "review PR #1", null, "Ship PR #269"]) {
    const a = agent({ parentAgentId: null, title });
    assert.equal(
      classifyWorkerPermissionRequest(a, externalDirectory({ patterns: ["/home/jorb/work/refdes/*"] }), POLICY)
        .action,
      "pending",
      `expected pending for title ${String(title)}`,
    );
  }
});

// ---------------------------------------------------------------------------
// Request gates and the retired Case 2 (command text is no longer a key).
// ---------------------------------------------------------------------------

test("non-opencode agents/requests and non-external_directory requests stay pending", () => {
  const ok = { patterns: ["/home/jorb/work/refdes/*"] };
  const cases: Array<[ClassifierAgent, ClassifierRequest]> = [
    [agent({ provider: "codex" }), externalDirectory(ok)],
    [agent(), { ...externalDirectory(ok), provider: "codex" }],
    [agent(), { ...externalDirectory(ok), name: "bash" }],
    [agent(), { ...externalDirectory(ok), kind: "command" }],
    [agent(), { ...externalDirectory(ok), kind: "question", name: "question" }],
  ];
  for (const [a, request] of cases) {
    assert.equal(classifyWorkerPermissionRequest(a, request, POLICY).action, "pending");
  }
});

test("safe-looking command text alone approves nothing (scope is patterns)", () => {
  const decision = allow({
    command: "cat /home/jorb/work/refdes/.scratch/PROGRESS.md",
    metadata: { command: "cat /home/jorb/work/refdes/in-prog-logs/x.txt", filepath: PROGRESS },
  });
  assert.equal(decision.action, "pending");
  const withScope = allow({
    patterns: ["/home/jorb/work/refdes/in-prog-logs/*"],
    command: "cat /home/jorb/work/refdes/in-prog-logs/x.txt",
  });
  assert.equal(withScope.action, "allow");
});

test("metadata filepath outside the roots does not veto in-root patterns (documented)", () => {
  const decision = allow({
    patterns: ["/home/jorb/work/refdes/in-prog-logs/*"],
    metadata: { filepath: "/home/jorb/.ssh/id_ed25519" },
  });
  assert.equal(decision.action, "allow");
});

// ---------------------------------------------------------------------------
// Round 3: glob metacharacters other than *, and symlink escapes.
// ---------------------------------------------------------------------------

test("glob metacharacters other than * are rejected; * stays allowed", () => {
  const base = "/home/jorb/work/refdes/";
  for (const bad of ["[", "]", "{", "}", "?", "!", "(", ")", "`", "~", "\\", "$", '"', "'", ";", "\0", "\n"]) {
    const decision = allow({ patterns: [`${base}a${bad}b`] });
    assert.equal(decision.action, "pending", `expected pending for metachar ${JSON.stringify(bad)}`);
  }
  for (const ok of [`${base}.scratch/*`, `${base}src/refdes/*`, WORKTREE_ROOT + "/*"]) {
    assert.equal(allow({ patterns: [ok] }).action, "allow", `expected allow for ${ok}`);
  }
});

test("glob-encoded .. probes are pending", () => {
  for (const patterns of [
    ["/home/jorb/work/refdes/[.][.]/etc/passwd"],
    ["/home/jorb/work/refdes/{..,x}/y"],
    ["/home/jorb/work/refdes/..\\/etc"],
    ["/home/jorb/work/refdes/a\\b"],
    ["/home/jorb/work/refdes/$HOME/x"],
  ]) {
    assert.equal(allow({ patterns }).action, "pending", `expected pending for ${patterns.join(",")}`);
  }
});

test("symlink escapes are caught by the injected resolver", () => {
  const realRoot = "/home/jorb/work/refdes";
  const mk = (realpath: (path: string) => string): PathResolver => ({
    realpath,
    childSymlinkEscapes: () => "clear",
  });
  const classifyWith = (patterns: string[], resolve: PathResolver) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), POLICY, resolve).action;

  const escaping = mk((path) => (path === `${realRoot}/link` ? "/outside/x" : path));
  assert.equal(classifyWith([`${realRoot}/link/*`], escaping), "pending");

  const internal = mk((path) => (path === `${realRoot}/link` ? `${realRoot}/in-prog-logs` : path));
  assert.equal(classifyWith([`${realRoot}/link/*`], internal), "allow");

  const throwing = mk(() => {
    throw new Error("ENOENT");
  });
  assert.equal(classifyWith([`${realRoot}/x/*`], throwing), "pending");

  const relocated = mk((path) =>
    path === realRoot ? "/data/refdes" : path.startsWith(`${realRoot}/`) ? `/data/refdes${path.slice(realRoot.length)}` : path,
  );
  assert.equal(classifyWith([`${realRoot}/in-prog-logs/*`], relocated), "allow");

  assert.equal(classifyWith([`${realRoot}/.scratch/*`], mk((path) => path)), "allow");
});

// ---------------------------------------------------------------------------
// Round 5 (P1): wildcards are narrowed to a final `*`, and the directory's
// direct children are checked for symlinks escaping the roots.
// ---------------------------------------------------------------------------

test("wildcard allowed only as the exact final segment", () => {
  const base = "/home/jorb/work/refdes";
  for (const patterns of [
    [`${base}/**`],
    [`${base}/src/**/*`],
    [`${base}/a*/b`],
    [`${base}/src*`],
    [`${base}/*.ts`],
    [`${base}/in-prog-logs/*/../x`],
  ]) {
    assert.equal(allow({ patterns }).action, "pending", `expected pending for ${patterns.join(",")}`);
  }
  assert.equal(allow({ patterns: [`${base}/src/*`] }).action, "allow");
});

test("wildcard dir child check: clear/escape/inside/too-many/throw", () => {
  const base = "/home/jorb/work/refdes";
  const mk = (childSymlinkEscapes: PathResolver["childSymlinkEscapes"]): PathResolver => ({
    realpath: (path) => path,
    childSymlinkEscapes,
  });
  const classifyWith = (patterns: string[], resolve: PathResolver) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), POLICY, resolve).action;

  // no symlink children -> allowed
  assert.equal(classifyWith([`${base}/.scratch/*`], mk(() => "clear")), "allow");
  // escaping symlink child -> pending
  assert.equal(classifyWith([`${base}/.scratch/*`], mk(() => "escape")), "pending");
  // symlink child staying inside the roots: the fs resolver reports "clear"
  // for that dir (a target inside the roots is not an escape) -> allowed
  const insideChild: PathResolver = {
    realpath: (path) => path,
    childSymlinkEscapes: (dir, roots) =>
      roots.some((root) => dir === root || dir.startsWith(`${root}/`)) ? "clear" : "escape",
  };
  assert.equal(classifyWith([`${base}/probe/*`], insideChild), "allow");
  // too many entries -> pending
  assert.equal(classifyWith([`${base}/.scratch/*`], mk(() => "too-many")), "pending");
  // resolver throwing (fs error) -> pending
  assert.equal(
    classifyWith(
      [`${base}/.scratch/*`],
      mk(() => {
        throw new Error("EIO");
      }),
    ),
    "pending",
  );
});

test("default resolver: plain patterns unchanged, wildcards pending", () => {
  const classify = (patterns: string[]) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), POLICY).action;
  assert.equal(classify([`${PROGRESS}`]), "allow");
  assert.equal(classify([`${WORKTREE_ROOT}/feat-x/in-prog-logs/*`]), "pending");
});

test("round-4 limit is now enforced: probe/* with an escaping child is pending", () => {
  const realRoot = "/home/jorb/work/refdes";
  const resolver: PathResolver = {
    realpath: (path) => path,
    childSymlinkEscapes: (dir) => (dir === `${realRoot}/probe` ? "escape" : "clear"),
  };
  const classify = (patterns: string[]) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), POLICY, resolver).action;
  assert.equal(classify([`${realRoot}/probe/*`]), "pending");
  assert.equal(classify([`${realRoot}/probe/**`]), "pending");
  assert.equal(classify([`${realRoot}/probe/*/*/*`]), "pending");
  assert.equal(classify([`${realRoot}/other/*`]), "allow");
});

test("real fs resolver: symlinked child escaping to /etc blocks the wildcard", () => {
  const scratch = fileURLToPath(new URL("../../../.scratch", import.meta.url));
  mkdirSync(scratch, { recursive: true });
  const base = realpathSync(mkdtempSync(path.join(scratch, "fs-resolver-")));
  const probe = path.join(base, "probe");
  const clean = path.join(base, "clean");
  mkdirSync(probe);
  mkdirSync(clean);
  symlinkSync("/etc", path.join(probe, "link"));
  const resolver = createFsResolver();
  assert.equal(resolver.childSymlinkEscapes(probe, [base]), "escape");
  assert.equal(resolver.childSymlinkEscapes(clean, [base]), "clear");
  assert.equal(resolver.childSymlinkEscapes(path.join(base, "missing"), [base]), "clear");
  const localPolicy: WorkerPermissionPolicy = { ...POLICY, roots: [base] };
  const classify = (patterns: string[]) =>
    classifyWorkerPermissionRequest(agent(), externalDirectory({ patterns }), localPolicy, resolver).action;
  assert.equal(classify([`${probe}/*`]), "pending");
  assert.equal(classify([`${clean}/*`]), "allow");
});
