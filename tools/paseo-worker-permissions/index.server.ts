import type { PluginServerContext } from "@getpaseo/plugin/server";
import { classifyWorkerPermissionRequest } from "./shared/classifier";

/**
 * Server-only plugin: answers ONLY Sol-dispatched OpenCode workers'
 * `external_directory` permission requests that the shared/classifier
 * allowlist covers (exact shared PROGRESS.md file, read-only cat/head/rg
 * over in-prog-logs evidence paths). Every other request is left pending
 * for a human. Nothing is auto-denied, auto-approved for other parents,
 * other providers, other permissions, writes to source, questions, plans,
 * mode changes, or arbitrary directory scopes.
 */
export default function contribute(server: PluginServerContext) {
  const remove = server.on("agent.permission_requested", async (event, context) => {
    const decision = classifyWorkerPermissionRequest(
      {
        provider: event.agent.provider,
        parentAgentId: event.agent.parentAgentId,
      },
      {
        provider: event.request.provider,
        name: event.request.name,
        kind: event.request.kind,
        input: event.request.input,
      },
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
