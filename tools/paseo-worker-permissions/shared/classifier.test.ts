import assert from "node:assert/strict";
import { test } from "node:test";

import {
  classifyWorkerPermissionRequest,
  type ClassifierAgent,
  type ClassifierRequest,
  WORKER_PERMISSION_POLICY,
} from "./classifier.ts";

const SOL: ClassifierAgent = { provider: "opencode", parentAgentId: WORKER_PERMISSION_POLICY.parentAgentId };
const PROGRESS = WORKER_PERMISSION_POLICY.progressFile;
const LOGS = "/home/jorb/work/refdes/in-prog-logs";

function toolRequest(
  name: string,
  input: Record<string, unknown> | undefined,
  kind = "tool",
  provider = "opencode",
): ClassifierRequest {
  return { provider, name, kind, input };
}

function externalDirectory(input: Record<string, unknown> | undefined): ClassifierRequest {
  return toolRequest("external_directory", input);
}

test("allows read of the exact shared progress file", () => {
  const decision = classifyWorkerPermissionRequest(
    SOL,
    externalDirectory({ patterns: ["/home/jorb/work/refdes/.scratch/*"], metadata: { filepath: PROGRESS } }),
  );
  assert.equal(decision.action, "allow");
});

test("allows edit/write of the exact progress file via nested metadata.input", () => {
  const decision = classifyWorkerPermissionRequest(
    SOL,
    externalDirectory({ metadata: { input: { filepath: PROGRESS }, title: "Edit" } }),
  );
  assert.equal(decision.action, "allow");
});

test("allows cat on an in-prog-logs file", () => {
  const decision = classifyWorkerPermissionRequest(
    SOL,
    externalDirectory({ command: `cat ${LOGS}/worker-permission-policy.txt` }),
  );
  assert.equal(decision.action, "allow");
});

test("allows head with numeric flags on evidence files", () => {
  for (const command of [
    `head -20 ${LOGS}/a.txt`,
    `head -n 5 ${LOGS}/a.txt`,
    `head -n 5 ${LOGS}/a.txt ${PROGRESS}`,
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "allow", command);
  }
});

test("allows rg over evidence roots, pattern plus explicit paths", () => {
  for (const command of [
    `rg worker ${LOGS}`,
    `rg -n -i worker ${LOGS}/a.txt`,
    `rg -C 2 worker ${LOGS} ${PROGRESS}`,
    `rg -e wo--rd ${LOGS}`,
    `rg --color never worker ${LOGS}`,
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "allow", command);
  }
});

test("reads command from nested metadata input like the daemon adapter does", () => {
  const decision = classifyWorkerPermissionRequest(
    SOL,
    externalDirectory({ metadata: { input: { command: `cat ${LOGS}/a.txt` } } }),
  );
  assert.equal(decision.action, "allow");
});

test("stays pending for any other parent agent", () => {
  for (const parentAgentId of [null, "11111111-1111-1111-1111-111111111111", undefined]) {
    const decision = classifyWorkerPermissionRequest(
      { provider: "opencode", parentAgentId: parentAgentId ?? null },
      externalDirectory({ metadata: { filepath: PROGRESS } }),
    );
    assert.equal(decision.action, "pending", String(parentAgentId));
  }
});

test("stays pending for other providers", () => {
  const decision = classifyWorkerPermissionRequest(
    { provider: "codex", parentAgentId: SOL.parentAgentId },
    externalDirectory({ metadata: { filepath: PROGRESS } }),
  );
  assert.equal(decision.action, "pending");
});

test("stays pending for other permission names and kinds", () => {
  assert.equal(
    classifyWorkerPermissionRequest(SOL, toolRequest("bash", { command: `cat ${LOGS}/a.txt` })).action,
    "pending",
  );
  assert.equal(
    classifyWorkerPermissionRequest(SOL, toolRequest("edit", { metadata: { filepath: PROGRESS } })).action,
    "pending",
  );
  assert.equal(
    classifyWorkerPermissionRequest(
      SOL,
      toolRequest("question", undefined, "question"),
    ).action,
    "pending",
  );
});

test("stays pending when metadata has no usable filepath or command", () => {
  assert.equal(
    classifyWorkerPermissionRequest(SOL, externalDirectory({ patterns: [`${LOGS}/*`] })).action,
    "pending",
  );
  assert.equal(classifyWorkerPermissionRequest(SOL, externalDirectory(undefined)).action, "pending");
});

test("stays pending for a filepath that is not the progress file", () => {
  for (const filepath of [
    "/home/jorb/work/refdes/src/refdes/model.py",
    `${LOGS}/a.txt`,
    `${PROGRESS}.evil`,
    "/home/jorb/work/refdes/.scratch/other.md",
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ metadata: { filepath } }));
    assert.equal(decision.action, "pending", filepath);
  }
});

test("stays pending for glob-shaped filepaths", () => {
  const decision = classifyWorkerPermissionRequest(
    SOL,
    externalDirectory({ metadata: { filepath: "/home/jorb/work/refdes/.scratch/PROGRESS*" } }),
  );
  assert.equal(decision.action, "pending");
});

test("stays pending on redirections, pipes, chaining, and substitutions", () => {
  for (const command of [
    `cat ${LOGS}/a.txt > /home/jorb/work/refdes/src/refdes/x.py`,
    `cat ${LOGS}/a.txt; rm -rf /home/jorb/work/refdes`,
    `cat ${LOGS}/a.txt | sh`,
    `cat ${LOGS}/a.txt && rm -rf /home/jorb/work/refdes/.scratch`,
    `cat ${LOGS}/$(whoami).txt`,
    "cat a.txt\nrm -rf /",
    `cat ${LOGS}/a.txt &`,
    "cat `whoami`.txt",
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "pending", command);
  }
});

test("stays pending on quoting and shell wrappers", () => {
  for (const command of [
    `cat "${LOGS}/a.txt"`,
    "bash -c 'cat x'",
    `sh -c "cat ${LOGS}/a.txt"`,
    `env cat ${LOGS}/a.txt`,
    `echo hi > ${PROGRESS}`,
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "pending", command);
  }
});

test("stays pending for unapproved flags that can execute code or read files", () => {
  for (const command of [
    `rg --pre /bin/sh worker ${LOGS}`,
    `rg --hostname-bin /bin/sh worker ${LOGS}`,
    `rg -f /home/jorb/work/refdes/patterns ${LOGS}`,
    `rg --config /home/jorb/evil.toml worker ${LOGS}`,
    `cat --help ${LOGS}/a.txt`,
    `head -n -5 ${LOGS}/a.txt`,
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "pending", command);
  }
});

test("stays pending for paths outside the evidence roots", () => {
  for (const command of [
    `cat /home/jorb/work/refdes/src/refdes/model.py`,
    `rg worker /home/jorb/work/refdes`,
    `rg worker /home/jorb/work/refdes/.scratch`,
    `cat /home/jorb/work/refdes/in-prog-logs/../src/refdes/model.py`,
    `rg worker ${LOGS} /etc/passwd`,
  ]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "pending", command);
  }
});

test("stays pending when the read command has no explicit path argument", () => {
  for (const command of ["cat", "head", "rg", `rg worker`, `head -n 5`]) {
    const decision = classifyWorkerPermissionRequest(SOL, externalDirectory({ command }));
    assert.equal(decision.action, "pending", command);
  }
});
