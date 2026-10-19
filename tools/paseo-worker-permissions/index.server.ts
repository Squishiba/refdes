import { readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import type { PluginServerContext } from "@getpaseo/plugin/server";
import {
  WORKER_PERMISSION_POLICY,
  classifyWorkerPermissionRequest,
  type WorkerPermissionPolicy,
} from "./shared/classifier";

/**
 * Server-only plugin: answers OpenCode `external_directory` permission
 * requests of refdes workers ONLY when the requesting agent is a child of a
 * dispatcher on the parents.json allowlist (or a PR-review reviewer by
 * title) AND every entry of the request's `input.patterns` — the scope that
 * is actually released — is glob-safe (no metacharacters beyond `*`) and
 * sits inside the allowlisted roots, symlinks resolved via realpath at
 * check time. Every other request is left pending for a human. Nothing is
 * auto-denied.
 */

const PLUGIN_ID = "refdes-worker-permissions";

function parentsFilePath(): string {
  const override = process.env.REFDES_WORKER_PERMISSIONS_PARENTS_FILE;
  if (override && override.length > 0) return override;
  const paseoHome =
    process.env.PASEO_HOME && process.env.PASEO_HOME.length > 0
      ? process.env.PASEO_HOME
      : path.join(homedir(), ".paseo");
  return path.join(paseoHome, "plugin-settings", PLUGIN_ID, "parents.json");
}

function readParentAgentIds(): readonly string[] {
  let raw: string;
  try {
    raw = readFileSync(parentsFilePath(), "utf8");
  } catch {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return [];
    const ids = (parsed as Record<string, unknown>).parentAgentIds;
    if (!Array.isArray(ids)) return [];
    if (!ids.every((id) => typeof id === "string" && id.length > 0)) return [];
    return ids as string[];
  } catch {
    return [];
  }
}

export default function contribute(server: PluginServerContext) {
  const remove = server.on("agent.permission_requested", async (event, context) => {
    const policy: WorkerPermissionPolicy = {
      ...WORKER_PERMISSION_POLICY,
      parentAgentIds: readParentAgentIds(),
    };
    const decision = classifyWorkerPermissionRequest(
      {
        provider: event.agent.provider,
        parentAgentId: event.agent.parentAgentId,
        title: event.agent.title,
      },
      {
        provider: event.request.provider,
        name: event.request.name,
        kind: event.request.kind,
        input: event.request.input,
      },
      policy,
      (pathToResolve) => realpathSync(pathToResolve),
    );
    if (decision.action !== "allow") {
      return;
    }
    console.log(
      `auto-allow external_directory for agent ${event.agent.id} ` +
        `(request ${event.request.id}): ${decision.reason}`,
    );
    try {
      await context.paseo.agents.ref(event.agent.id).respondToPermission({
        requestId: event.request.id,
        response: { behavior: "allow" },
      });
    } catch (error) {
      // The human may have answered first; leaving a resolved request alone
      // is correct, and a pending one stays pending on failure.
      console.error(
        `respondToPermission failed for request ${event.request.id}: ` +
          `${error instanceof Error ? error.message : String(error)}`,
      );
    }
  });
  return () => {
    remove();
  };
}
