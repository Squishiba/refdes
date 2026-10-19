/**
 * Fail-closed permission classifier for refdes Qwen fix workers.
 *
 * The 2026-10-17 security review found that deciding on request *metadata*
 * (a `filepath`, a command text) approves a scope the classifier never
 * inspects: the scope OpenCode actually releases is `request.input.patterns`
 * (verified in the installed daemon adapter, providers/opencode-agent.js
 * `appendOpenCodePermissionAsked`: `input = {patterns, metadata, tool,
 * command}`). This classifier therefore decides on the real scope:
 *
 *  - Identity: the agent's parentAgentId is on the allowlist built from the
 *    plugin's parents.json (see README; absent/invalid file -> empty list ->
 *    nothing approved), or the agent's title starts with the PR-review
 *    reviewer prefix ("Review PR "), exposed by PluginHookAgent.title.
 *  - Scope: `request.input.patterns` is a non-empty array of strings; every
 *    entry is absolute, has no ".." segment, contains no glob metacharacter
 *    other than `*`, and sits inside one of the allowlisted roots at a
 *    path-segment boundary (root itself, or root + "/..."). A `*` is allowed
 *    ONLY as the exact final path segment (`<dir>/*`): `**`, a mid-path `*`,
 *    and `a*b` are pending. The LITERAL directory prefix is realpath'd
 *    (injectable PathResolver): a symlink in the literal prefix that points
 *    outside a root fails closed. For a `<dir>/*` pattern the resolver is
 *    additionally asked whether any DIRECT child of <dir> is a symlink whose
 *    real target lies outside the roots (escape / too-many / resolver error
 *    -> pending; a resolver that cannot answer wildcards -> pending; missing
 *    dir = no children = clear). The default resolver answers no wildcard
 *    checks, so wildcards are pending unless the caller supplies a real one.
 *    A request is approved only when ALL patterns pass.
 *
 * The old metadata-keyed cases are retired: the root allowlist subsumes the
 * exact-progress-file case, and a command text is no longer an approval key
 * by itself (a bash request is approved iff its patterns pass). Everything
 * else stays pending for a human; nothing is ever auto-denied.
 *
 * This module is pure (no Node, no SDK runtime imports) so it is
 * unit-testable from the shared runtime boundary; index.server.ts adapts the
 * hook event and supplies the file-backed parent allowlist.
 */

export const WORKER_PERMISSION_POLICY = {
  provider: "opencode",
  permission: "external_directory",
  /** PR-review plugin reviewer agents are matched by this title prefix. */
  reviewerTitlePrefix: "Review PR ",
  /** Parent dispatcher ids; index.server.ts fills this from parents.json. */
  parentAgentIds: [] as readonly string[],
  /** The only directory scopes the plugin may ever release. */
  roots: [
    "/home/jorb/.paseo/worktrees/16msma8v",
    "/home/jorb/work/refdes",
    "/home/jorb/work/venv-refdes",
  ] as const,
} as const;

export interface WorkerPermissionPolicy {
  provider: string;
  permission: string;
  reviewerTitlePrefix: string;
  parentAgentIds: readonly string[];
  roots: readonly string[];
}

export type ClassifierDecision =
  | { action: "allow"; reason: string }
  | { action: "pending"; reason: string };

/**
 * Filesystem view used by the scope checks (fs-backed in production).
 * - realpath: resolves a path through symlinks; THROWS for paths that do
 *   not exist (the classifier then walks up to the deepest existing
 *   ancestor).
 * - childSymlinkEscapes: inspects DIRECT children of `dir` (realpath'd,
 *   passed as `resolvedRoots`): "escape" if any child symlink resolves
 *   outside the roots, "clear" if none does (a missing dir has no children
 *   = "clear"), "too-many" above the entry budget, THROWS when the answer
 *   cannot be determined (a resolver error fails closed).
 * The default resolver is identity and answers no wildcard checks, so a
 * wildcard pattern stays pending unless the caller supplies a real resolver.
 */
export interface PathResolver {
  realpath(path: string): string;
  childSymlinkEscapes(dir: string, resolvedRoots: readonly string[]): "clear" | "escape" | "too-many";
}

const DEFAULT_PATH_RESOLVER: PathResolver = {
  realpath: (path: string) => path,
  childSymlinkEscapes: () => {
    throw new Error("resolver cannot inspect child symlinks");
  },
};

/** Structural subset of the hook's PluginHookAgent. */
export interface ClassifierAgent {
  provider: string;
  parentAgentId: string | null;
  title: string | null;
}

/** Structural subset of AgentPermissionRequest (kind "tool" path). */
export interface ClassifierRequest {
  provider: string;
  name: string;
  kind: string;
  input?: Record<string, unknown> | undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasDotSegment(path: string): boolean {
  return path.split("/").includes("..");
}

function insideRoots(path: string, roots: readonly string[]): boolean {
  return roots.some((root) => path === root || path.startsWith(`${root}/`));
}

/**
 * One pattern entry: absolute, no traversal, at or inside one of the roots,
 * and no glob metacharacter other than `*` — the daemon matcher expands
 * character classes, braces, `?`, `!`, and extglob groups, so
 * `[.][.]/etc` and `{..,x}/y` smuggle traversal past a lexical check, and
 * backslash escapes the next character. `$`, quotes, and `;` are rejected
 * too: no legitimate pattern needs them (round-3b probe review). `*` is
 * allowed ONLY as the exact final path segment (round-5 P1: a wildcard is
 * the only shape whose matched set the classifier can bound, by listing
 * the directory's direct children).
 */
function patternScope(pattern: string, roots: readonly string[]): string | null {
  if (pattern.length === 0) return "empty pattern";
  if (!pattern.startsWith("/")) return `pattern is not absolute: ${pattern}`;
  if (hasDotSegment(pattern)) return `pattern has a .. segment: ${pattern}`;
  if (!insideRoots(pattern, roots)) {
    return `pattern is outside the allowlisted roots: ${pattern}`;
  }
  const meta = /[[\]{}?!()`~$"';\\\0\r\n]/.exec(pattern);
  if (meta !== null) {
    return `pattern has a glob metacharacter other than *: ${pattern}`;
  }
  const star = pattern.indexOf("*");
  if (star !== -1 && !(star === pattern.length - 1 && pattern.endsWith("/*"))) {
    return `wildcard only allowed as the final segment: ${pattern}`;
  }
  return null;
}

/** Directory of the pattern: literal prefix, with the final "/*" stripped. */
function scopePrefix(pattern: string): string {
  const base = pattern.endsWith("/*") ? pattern.slice(0, -2) : pattern;
  return base.length > 1 ? base.replace(/\/+$/, "") : "/";
}

/**
 * Resolve a pattern's directory prefix through symlinks: realpath the
 * deepest existing ancestor and check it against the realpaths of the
 * roots. For a `<dir>/*` pattern the resolver is also asked whether any
 * direct child of the resolved directory is a symlink escaping the roots.
 * Any resolver error (unresolvable prefix, unknown child answer) -> pending.
 */
function resolveScope(
  pattern: string,
  roots: readonly string[],
  resolver: PathResolver,
): { ok: true } | { ok: false; reason: string } {
  const resolvedRoots: string[] = [];
  for (const root of roots) {
    try {
      resolvedRoots.push(resolver.realpath(root));
    } catch {
      return { ok: false, reason: `allowlisted root cannot be resolved: ${root}` };
    }
  }
  let cursor = scopePrefix(pattern);
  for (;;) {
    let resolved: string;
    try {
      resolved = resolver.realpath(cursor);
    } catch {
      if (cursor === "/") {
        return { ok: false, reason: `pattern has no resolvable ancestor: ${pattern}` };
      }
      const cut = cursor.lastIndexOf("/");
      cursor = cut <= 0 ? "/" : cursor.slice(0, cut);
      continue;
    }
    if (!insideRoots(resolved, resolvedRoots)) {
      return { ok: false, reason: `pattern resolves outside the allowlisted roots: ${pattern} -> ${resolved}` };
    }
    if (pattern.includes("*")) {
      let children: "clear" | "escape" | "too-many";
      try {
        children = resolver.childSymlinkEscapes(resolved, resolvedRoots);
      } catch (error) {
        return {
          ok: false,
          reason: `child symlinks of ${resolved} cannot be inspected: ${
            error instanceof Error ? error.message : String(error)
          }`,
        };
      }
      if (children === "escape") {
        return { ok: false, reason: `a direct child symlink of ${resolved} escapes the allowlisted roots` };
      }
      if (children === "too-many") {
        return { ok: false, reason: `too many entries in ${resolved} to inspect safely` };
      }
    }
    return { ok: true };
  }
}

function identityReason(
  agent: ClassifierAgent,
  policy: WorkerPermissionPolicy,
): { ok: true; reason: string } | { ok: false; reason: string } {
  if (agent.parentAgentId !== null && policy.parentAgentIds.includes(agent.parentAgentId)) {
    return { ok: true, reason: `parent ${agent.parentAgentId} is on the dispatcher allowlist` };
  }
  if (typeof agent.title === "string" && agent.title.startsWith(policy.reviewerTitlePrefix)) {
    return { ok: true, reason: `PR-review reviewer title: ${agent.title}` };
  }
  return { ok: false, reason: "agent is not a child of an allowlisted dispatcher and has no reviewer title" };
}

export function classifyWorkerPermissionRequest(
  agent: ClassifierAgent,
  request: ClassifierRequest,
  policy: WorkerPermissionPolicy = WORKER_PERMISSION_POLICY,
  resolver: PathResolver = DEFAULT_PATH_RESOLVER,
): ClassifierDecision {
  if (agent.provider !== policy.provider) {
    return { action: "pending", reason: `provider not ${policy.provider}: ${agent.provider}` };
  }
  if (request.provider !== policy.provider) {
    return { action: "pending", reason: `request provider not ${policy.provider}: ${request.provider}` };
  }
  if (request.kind !== "tool" || request.name !== policy.permission) {
    return {
      action: "pending",
      reason: `not an external_directory tool request: ${request.kind}/${request.name}`,
    };
  }
  const identity = identityReason(agent, policy);
  if (!identity.ok) {
    return { action: "pending", reason: identity.reason };
  }

  const input = isRecord(request.input) ? request.input : undefined;
  const patterns = input?.patterns;
  if (!Array.isArray(patterns)) {
    return { action: "pending", reason: "request has no patterns array; the approved scope is unknown" };
  }
  if (patterns.length === 0) {
    return { action: "pending", reason: "request has an empty patterns array; the approved scope is unknown" };
  }
  for (const pattern of patterns) {
    if (typeof pattern !== "string") {
      return { action: "pending", reason: `pattern entry is not a string: ${JSON.stringify(pattern)}` };
    }
    const error = patternScope(pattern, policy.roots);
    if (error !== null) {
      return { action: "pending", reason: error };
    }
    const resolved = resolveScope(pattern, policy.roots, resolver);
    if (!resolved.ok) {
      return { action: "pending", reason: resolved.reason };
    }
  }
  return {
    action: "allow",
    reason: `${identity.reason}; all ${patterns.length} pattern(s) inside allowlisted roots: ${patterns.join(", ")}`,
  };
}
