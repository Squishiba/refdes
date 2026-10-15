/**
 * Fail-closed permission classifier for refdes Sol-Qwen fix workers.
 *
 * Scope, deliberately narrow (see README.md):
 *  - Only agents whose parentAgentId is the Sol dispatcher, and only
 *    OpenCode `external_directory` tool-permission requests.
 *  - Auto-allow only (a) requests whose metadata names the exact shared
 *    PROGRESS.md file, and (b) non-interactive `cat`/`head`/`rg` evidence
 *    reads whose every path argument is an in-prog-logs file (or the exact
 *    PROGRESS.md file), with no shell operators, redirections, substitutions,
 *    quotes, globs, or unapproved flags.
 *  - Everything else stays pending for a human. A missing/unknown field is
 *    "pending", never "allow".
 *
 * This module is pure (no Node, no SDK runtime imports) so it is unit-testable
 * from the shared runtime boundary; index.server.ts adapts the hook event.
 */

export const WORKER_PERMISSION_POLICY = {
  /** Sol's dispatcher agent: the only parent whose children get policy. */
  parentAgentId: "d86b9967-5a0c-41e5-8635-fca6170fdeaa",
  provider: "opencode",
  permission: "external_directory",
  /** The one exact shared progress file workers may touch. */
  progressFile: "/home/jorb/work/refdes/.scratch/PROGRESS.md",
  /** Read-only evidence roots (paths, never workspace membership). */
  evidenceRoots: ["/home/jorb/work/refdes/in-prog-logs/"] as const,
  commands: ["cat", "head", "rg"] as const,
} as const;

export type ClassifierDecision =
  | { action: "allow"; reason: string }
  | { action: "pending"; reason: string };

/** Structural subset of the hook's PluginHookAgent. */
export interface ClassifierAgent {
  provider: string;
  parentAgentId: string | null;
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

function readString(record: Record<string, unknown> | undefined, keys: string[]): string | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return null;
}

const FILEPATH_KEYS = ["filepath", "file", "path"];
const COMMAND_KEYS = ["command", "cmd", "shellCommand"];

/**
 * Extract the metadata record carrying tool input. The daemon adapter passes
 * OpenCode's raw metadata through at `input.metadata`, and command text at
 * `input.command`; OpenCode also nests tool input under `metadata.input`.
 */
function metadataOf(request: ClassifierRequest): Record<string, unknown> | undefined {
  const input = isRecord(request.input) ? request.input : undefined;
  const metadata = isRecord(input?.metadata) ? input.metadata : undefined;
  return metadata;
}

function nestedInputOf(metadata: Record<string, unknown> | undefined) {
  return isRecord(metadata?.input) ? metadata.input : undefined;
}

function exactProgressFileAction(request: ClassifierRequest): ClassifierDecision | null {
  const metadata = metadataOf(request);
  const filepath =
    readString(metadata, FILEPATH_KEYS) ?? readString(nestedInputOf(metadata), FILEPATH_KEYS);
  if (filepath === null) return null;
  if (filepath.includes("*") || filepath.includes("?")) {
    return { action: "pending", reason: `progress filepath is a pattern, not an exact file: ${filepath}` };
  }
  if (filepath === WORKER_PERMISSION_POLICY.progressFile) {
    return { action: "allow", reason: `exact shared progress file: ${filepath}` };
  }
  return { action: "pending", reason: `filepath is not the shared progress file: ${filepath}` };
}

/**
 * Shell metacharacter-free by construction: the command must match this
 * character class, which excludes ; | & > < ` $ ( ) { } [ ] * ? ! " ' \ and
 * newlines/tabs, so token splitting cannot reassemble an operator.
 */
const SAFE_COMMAND_CHARS = /^[A-Za-z0-9 ./_\-,:=%+@]+$/;

const CAT_FLAGS = new Set(["-b", "-n", "-s", "-E", "-T", "-v", "-A", "-t", "-e", "-u"]);
const HEAD_PLAIN_FLAGS = new Set(["-q", "-z", "-v", "-p"]);
const HEAD_VALUE_FLAGS = new Set(["-n", "-c"]);
const RG_PLAIN_FLAGS = new Set([
  "-i", "--ignore-case", "-F", "--fixed-strings", "-w", "--word-regexp",
  "-n", "--line-number", "-N", "--no-line-number", "-l", "--files-with-matches",
  "-c", "--count", "-S", "--smart-case", "-s", "--no-messages", "-I", "--no-ignore",
  "--hidden", "--no-heading", "-0", "--null", "-o", "--only-matching", "--no-config",
]);
const RG_COUNT_FLAGS = new Set(["-A", "-B", "-C", "-m", "--max-count"]);
const RG_PATTERN_FLAGS = new Set(["-e", "--regexp", "-g", "--glob"]);
const RG_VALUE_FLAGS = new Set(["--color"]);
const RG_COLOR_VALUES = new Set(["never", "auto", "always"]);

function isEvidencePath(token: string): boolean {
  if (token === WORKER_PERMISSION_POLICY.progressFile) return true;
  return WORKER_PERMISSION_POLICY.evidenceRoots.some(
    (root) => token === root.slice(0, -1) || token.startsWith(root),
  );
}

function hasDotSegment(token: string): boolean {
  return token.split("/").includes("..");
}

interface ScanState {
  pendingNumericFlag: boolean;
  pendingPatternFlag: boolean;
  pendingColorFlag: boolean;
  flagsDone: boolean;
  patternFromFlag: boolean;
}

/** Scan one non-command token; returns an error string, or null when ok. */
function scanToken(
  command: (typeof WORKER_PERMISSION_POLICY.commands)[number],
  token: string,
  state: ScanState,
  positionals: string[],
): string | null {
  if (state.pendingNumericFlag) {
    state.pendingNumericFlag = false;
    return /^\d+$/.test(token) ? null : `${command}: flag expects a number, got ${token}`;
  }
  if (state.pendingPatternFlag) {
    state.pendingPatternFlag = false;
    if (token.startsWith("-")) return `${command}: flag expects a pattern, got ${token}`;
    state.patternFromFlag = true;
    return null;
  }
  if (state.pendingColorFlag) {
    state.pendingColorFlag = false;
    return RG_COLOR_VALUES.has(token) ? null : `${command}: unsupported --color value ${token}`;
  }
  if (!state.flagsDone && token === "--") {
    state.flagsDone = true;
    return null;
  }
  if (!state.flagsDone && token.startsWith("-")) {
    if (command === "cat") {
      if (CAT_FLAGS.has(token)) return null;
      return `cat: flag not allowed: ${token}`;
    }
    if (command === "head") {
      if (/^-\d+$/.test(token)) return null;
      if (HEAD_PLAIN_FLAGS.has(token)) return null;
      if (HEAD_VALUE_FLAGS.has(token)) {
        state.pendingNumericFlag = true;
        return null;
      }
      return `head: flag not allowed: ${token}`;
    }
    if (RG_PLAIN_FLAGS.has(token)) return null;
    if (RG_COUNT_FLAGS.has(token)) {
      state.pendingNumericFlag = true;
      return null;
    }
    if (RG_PATTERN_FLAGS.has(token)) {
      state.pendingPatternFlag = true;
      return null;
    }
    if (RG_VALUE_FLAGS.has(token)) {
      state.pendingColorFlag = true;
      return null;
    }
    return `rg: flag not allowed: ${token}`;
  }
  positionals.push(token);
  return null;
}

function evidenceReadCommand(commandText: string): ClassifierDecision {
  if (!SAFE_COMMAND_CHARS.test(commandText)) {
    return { action: "pending", reason: "command contains shell metacharacters or quoting" };
  }
  const tokens = commandText.trim().split(/ +/).filter((token) => token.length > 0);
  const command = tokens[0];
  if (
    command !== "cat" &&
    command !== "head" &&
    command !== "rg"
  ) {
    return { action: "pending", reason: `command is not cat/head/rg: ${command ?? ""}` };
  }
  const state: ScanState = {
    pendingNumericFlag: false,
    pendingPatternFlag: false,
    pendingColorFlag: false,
    flagsDone: false,
    patternFromFlag: false,
  };
  const positionals: string[] = [];
  for (const token of tokens.slice(1)) {
    const error = scanToken(command, token, state, positionals);
    if (error) return { action: "pending", reason: error };
  }
  if (state.pendingNumericFlag || state.pendingPatternFlag || state.pendingColorFlag) {
    return { action: "pending", reason: `${command}: trailing flag with no value` };
  }
  // rg: first positional is the search pattern, the rest must be evidence
  // paths (all positionals are paths when the pattern came from -e);
  // require at least one explicit path. cat/head: every positional must be
  // an evidence path; require at least one.
  const usesPatternPositional = command === "rg" && !state.patternFromFlag;
  const paths = usesPatternPositional ? positionals.slice(1) : positionals;
  if (paths.length === 0) {
    return { action: "pending", reason: `${command}: no explicit evidence path argument` };
  }
  for (const path of paths) {
    if (hasDotSegment(path)) return { action: "pending", reason: `path traversal: ${path}` };
    if (!isEvidencePath(path)) {
      return { action: "pending", reason: `path outside evidence roots: ${path}` };
    }
  }
  return { action: "allow", reason: `${command}: read-only over evidence paths only` };
}

export function classifyWorkerPermissionRequest(
  agent: ClassifierAgent,
  request: ClassifierRequest,
): ClassifierDecision {
  if (agent.provider !== WORKER_PERMISSION_POLICY.provider) {
    return { action: "pending", reason: `provider not opencode: ${agent.provider}` };
  }
  if (request.provider !== WORKER_PERMISSION_POLICY.provider) {
    return { action: "pending", reason: `request provider not opencode: ${request.provider}` };
  }
  if (agent.parentAgentId !== WORKER_PERMISSION_POLICY.parentAgentId) {
    return { action: "pending", reason: "agent parent is not the Sol dispatcher" };
  }
  if (request.kind !== "tool" || request.name !== WORKER_PERMISSION_POLICY.permission) {
    return {
      action: "pending",
      reason: `not an external_directory tool request: ${request.kind}/${request.name}`,
    };
  }

  const exactFile = exactProgressFileAction(request);
  if (exactFile !== null) return exactFile;

  const input = isRecord(request.input) ? request.input : undefined;
  const metadata = metadataOf(request);
  const command =
    readString(input, COMMAND_KEYS) ??
    readString(metadata, COMMAND_KEYS) ??
    readString(nestedInputOf(metadata), COMMAND_KEYS);
  if (command === null) {
    return {
      action: "pending",
      reason: "payload has neither an exact progress filepath nor a command text",
    };
  }
  return evidenceReadCommand(command);
}
