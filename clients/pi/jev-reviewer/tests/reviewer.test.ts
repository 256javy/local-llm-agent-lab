import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  writeFileSync,
  rmSync,
  symlinkSync,
  statSync,
  readFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { validateConfig } from "../src/config.ts";
import { Reviewer } from "../src/reviewer.ts";
import { Journal } from "../src/journal.ts";
import { report, readRecords } from "../src/report.ts";
import { scopedPath } from "../src/state.ts";
import type {
  Action,
  Config,
  ReviewerClient,
  ReviewResponse,
} from "../src/contracts.ts";
const conflict: ReviewResponse = {
  model: "mock",
  usage: { input_tokens: 20, output_tokens: 5 },
  judgments: [
    {
      pattern: "task_conflict",
      reference: "R1",
      choice: "problem",
      confidence: 0.99,
      probabilities: { problem: 0.99, useful: 0.005, uncertain: 0.005 },
    },
  ],
};
const action: Action = {
  toolCallId: "c1",
  toolName: "bash",
  input: { command: "npm install forbidden" },
};
function setup(
  t: TestContext,
  override: Partial<Config> = {},
  client?: ReviewerClient,
) {
  const root = mkdtempSync(join(tmpdir(), "jev-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  writeFileSync(join(root, "a.txt"), "Contenido vigente\n");
  const config = validateConfig({
    mode: "enforce",
    reviewer: "jev",
    requirements: [{ id: "R1", text: "No añadir dependencias." }],
    scope: {
      root,
      paths: ["a.txt", "new.txt"],
      allowBash: true,
      authorization: "Prueba sintética.",
    },
    calibration: [
      {
        pattern: "task_conflict",
        tool: "bash",
        threshold: 0.95,
        reference: "test-only",
      },
    ],
    ...override,
  });
  const records: Record<string, unknown>[] = [];
  let calls = 0;
  const reviewer = new Reviewer(
    config,
    async (s, signal) => {
      calls++;
      return client ? client(s, signal) : structuredClone(conflict);
    },
    (r) => records.push(r),
  );
  reviewer.state.sessionId = "session";
  reviewer.state.branchId = "branch";
  reviewer.state.input("Corregir sin añadir dependencias.");
  return { root, config, reviewer, records, calls: () => calls };
}
// Input snapshots and callbacks are exercised independently of model quality.
for (const mode of ["off", "observe", "enforce"] as const)
  test(`switch ${mode}`, async (t) => {
    const f = setup(t, { mode });
    const original = structuredClone(action);
    const d = await f.reviewer.review(action, f.root);
    assert.equal(f.calls(), mode === "off" ? 0 : 1);
    assert.equal(d.action, mode === "enforce" ? "block" : "allow");
    assert.equal(d.wouldBlock, mode !== "off");
    assert.deepEqual(action, original);
  });
test("brazo off prevalece incluso en enforce", async (t) => {
  const f = setup(t, { reviewer: "off" });
  assert.equal((await f.reviewer.review(action, f.root)).action, "allow");
  assert.equal(f.calls(), 0);
});
test("sin calibración no bloquea", async (t) => {
  const f = setup(t, { calibration: [] });
  const d = await f.reviewer.review(action, f.root);
  assert.equal(d.action, "allow");
  assert.equal(d.wouldBlock, false);
});
test("fallo y circuito permiten continuar sin consultas ilimitadas", async (t) => {
  const f = setup(t, {}, async () => {
    throw new Error("429 secret-not-logged");
  });
  for (let i = 0; i < 5; i++)
    assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  assert.equal(f.calls(), 3);
  assert.ok(!JSON.stringify(f.records).includes("secret-not-logged"));
});
test("deadline limita incluso un cliente que ignora AbortSignal", async (t) => {
  const f = setup(t, { deadlineMs: 15 }, async () => new Promise(() => {}));
  const start = performance.now();
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  assert.ok(performance.now() - start < 500);
});
test("cancelación del usuario no se considera fallo remoto", async (t) => {
  const f = setup(
    t,
    {},
    async (_s, signal) =>
      new Promise((_, reject) =>
        signal.addEventListener("abort", () => reject(new Error("abort"))),
      ),
  );
  const controller = new AbortController();
  const pending = f.reviewer.review(action, f.root, controller.signal);
  controller.abort();
  assert.equal((await pending).reason, "cancelled");
  assert.equal(f.reviewer.failures, 0);
});
test("recarga invalida respuestas tardías", async (t) => {
  let finish!: (r: ReviewResponse) => void;
  const f = setup(
    t,
    {},
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const pending = f.reviewer.review(action, f.root);
  f.reviewer.reset(true);
  finish(conflict);
  assert.equal((await pending).action, "abstain");
  assert.equal(f.reviewer.blocks, 0);
});
test("límite de consultas", async (t) => {
  const f = setup(t, { maxCallsPerTask: 1, mode: "observe" });
  await f.reviewer.review(action, f.root);
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  assert.equal(f.calls(), 1);
});
test("reintento equivalente permite continuar y no consume otra consulta", async (t) => {
  const f = setup(t);
  assert.equal((await f.reviewer.review(action, f.root)).action, "block");
  f.reviewer.state.result(action, [], true, {});
  assert.equal(
    (await f.reviewer.review({ ...action, toolCallId: "retry" }, f.root))
      .action,
    "allow",
  );
  assert.equal(f.calls(), 1);
});
test("allow-once se invalida al cambiar el objetivo", async (t) => {
  const f = setup(t);
  const d = await f.reviewer.review(action, f.root);
  assert.equal(f.reviewer.allowOnce(d.reviewId), true);
  f.reviewer.reset();
  f.reviewer.state.input("Nueva restricción.");
  assert.equal(f.reviewer.allowOnce(d.reviewId), false);
  assert.equal((await f.reviewer.review(action, f.root)).action, "block");
});
test("límite total de bloqueos", async (t) => {
  const f = setup(t, { maxBlocksPerTask: 1 });
  await f.reviewer.review(action, f.root);
  const d = await f.reviewer.review(
    { ...action, input: { command: "npm install another" } },
    f.root,
  );
  assert.equal(d.action, "allow");
  assert.equal(f.calls(), 1);
});
test("journal fallido nunca causa bloqueo", async (t) => {
  const f = setup(t);
  const r = new Reviewer(
    f.config,
    async () => conflict,
    () => {
      throw new Error("disk");
    },
  );
  r.state.input("Objetivo");
  assert.equal((await r.review(action, f.root)).action, "abstain");
  assert.equal(r.blocks, 0);
});
for (const toolName of ["read", "edit", "write"])
  test(`adaptador ${toolName} y requisito`, async (t) => {
    const f = setup(t, {
      calibration: [
        {
          pattern: "task_conflict",
          tool: toolName as "read" | "edit" | "write",
          threshold: 0.9,
          reference: "test",
        },
      ],
    });
    assert.equal(
      (
        await f.reviewer.review(
          {
            ...action,
            toolName,
            input:
              toolName === "read"
                ? { path: "new.txt" }
                : toolName === "edit"
                  ? { path: "new.txt", edits: [{ oldText: "a", newText: "b" }] }
                  : { path: "new.txt", content: "sintético" },
          },
          f.root,
        )
      ).action,
      "block",
    );
  });
test("nuevo archivo no necesita lectura previa", async (t) => {
  const f = setup(t, {}, async () => ({ ...conflict, judgments: [] }));
  assert.equal(
    (
      await f.reviewer.review(
        {
          ...action,
          toolName: "write",
          input: { path: "new.txt", content: "hola" },
        },
        f.root,
      )
    ).action,
    "allow",
  );
});
for (const mutation of ["reference", "confidence", "probabilities"] as const)
  test(`respuesta inválida ${mutation}`, async (t) => {
    const response = structuredClone(conflict);
    if (mutation === "reference") response.judgments[0].reference = "invented";
    if (mutation === "confidence") response.judgments[0].confidence = NaN;
    if (mutation === "probabilities")
      response.judgments[0].probabilities = { problem: 99 };
    const f = setup(t, {}, async () => response);
    assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  });
test("scope excluye .env, rutas externas, symlinks y cwd distinto", async (t) => {
  const f = setup(t);
  f.config.scope!.paths.push(".env", "link");
  writeFileSync(join(f.root, ".env"), "TOKEN=synthetic");
  symlinkSync("/etc/hosts", join(f.root, "link"));
  for (const path of [".env", "link", "../outside", "/etc/hosts"]) {
    const d = await f.reviewer.review(
      { ...action, toolName: "read", input: { path } },
      f.root,
    );
    assert.equal(d.action, "abstain");
    assert.deepEqual(d.snapshot.action.input, {});
  }
  assert.equal(scopedPath(f.config, tmpdir(), "a.txt"), undefined);
  assert.equal(f.calls(), 0);
});
test("sin autorización no envía ni almacena payload", async (t) => {
  const f = setup(t, { scope: undefined });
  const d = await f.reviewer.review(action, f.root);
  assert.equal(f.calls(), 0);
  assert.equal(d.action, "abstain");
  assert.equal(d.snapshot.objective.length, 0);
});
test("contexto excedido se abstiene sin recortar", async (t) => {
  const f = setup(t, { maxInputBytes: 50 });
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  assert.equal(f.calls(), 0);
});
function readAction(id = "read1", offset?: number): Action {
  return {
    toolCallId: id,
    toolName: "read",
    input: { path: "a.txt", ...(offset ? { offset } : {}) },
  };
}
function successfulRead(f: ReturnType<typeof setup>, details: unknown = {}) {
  const a = readAction();
  f.reviewer.state.before(a, f.root);
  f.reviewer.state.result(
    a,
    [{ type: "text", text: "Contenido vigente\n" }],
    false,
    details,
  );
}
const local: Partial<Config> = {
  reviewer: "local",
  calibration: [
    {
      pattern: "redundant_read",
      tool: "read",
      threshold: 1,
      reference: "test-only",
    },
  ],
};
test("brazo local identifica lectura exacta sin red", async (t) => {
  const f = setup(t, local);
  successfulRead(f);
  assert.equal(
    (await f.reviewer.review(readAction("r2"), f.root)).action,
    "block",
  );
  assert.equal(f.calls(), 0);
});
test("rango diferente no se bloquea", async (t) => {
  const f = setup(t, local);
  successfulRead(f);
  assert.equal(
    (await f.reviewer.review(readAction("r2", 2), f.root)).action,
    "allow",
  );
});
test("cambio externo invalida evidencia", async (t) => {
  const f = setup(t, local);
  successfulRead(f);
  writeFileSync(join(f.root, "a.txt"), "Nuevo contenido");
  assert.equal(
    (await f.reviewer.review(readAction("r2"), f.root)).action,
    "allow",
  );
});
test("archivo cambia durante consulta remota", async (t) => {
  let finish!: (r: ReviewResponse) => void;
  const f = setup(
    t,
    {},
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  successfulRead(f);
  const pending = f.reviewer.review(action, f.root);
  writeFileSync(join(f.root, "a.txt"), "Cambiado");
  finish(conflict);
  assert.equal((await pending).action, "abstain");
});
test("truncamiento no es evidencia", async (t) => {
  const f = setup(t, local);
  successfulRead(f, { truncation: { truncated: true } });
  assert.equal(f.reviewer.state.evidence.length, 0);
});
test("error de lectura no es evidencia", (t) => {
  const f = setup(t);
  const a = readAction();
  f.reviewer.state.before(a, f.root);
  f.reviewer.state.result(a, [{ type: "text", text: "Error" }], true, {});
  assert.equal(f.reviewer.state.evidence.length, 0);
});
test("hermanas pendientes provocan abstención", async (t) => {
  const f = setup(t);
  f.reviewer.state.before(readAction(), f.root);
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  assert.equal(f.calls(), 0);
});
test("bash invalida lecturas; tests tras cambios se permiten", async (t) => {
  const f = setup(t, local);
  successfulRead(f);
  f.reviewer.state.before(action, f.root);
  f.reviewer.state.result(action, [], false, {});
  assert.equal(f.reviewer.state.evidence.length, 0);
  assert.equal(
    (
      await f.reviewer.review(
        { ...action, input: { command: "node check.cjs" } },
        f.root,
      )
    ).action,
    "allow",
  );
});
test("compaction/fork empiezan sin objetivo y se abstienen", async (t) => {
  const f = setup(t);
  successfulRead(f);
  f.reviewer.reset(true);
  assert.equal(f.reviewer.state.evidence.length, 0);
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
});
test("journal privado y reporte determinista enlazan IDs", async (t) => {
  const f = setup(t);
  const journal = new Journal(join(f.root, ".local"), "session", "branch");
  const r = new Reviewer(f.config, async () => conflict, journal.write);
  r.state.input("Objetivo");
  const d = await r.review(action, f.root);
  const path = join(journal.directory, "events.jsonl");
  assert.equal(statSync(path).mode & 0o777, 0o600);
  assert.equal(statSync(journal.directory).mode & 0o777, 0o700);
  const records = readRecords(path);
  assert.equal(records[0].reviewId, d.reviewId);
  assert.deepEqual(report(records), report(records));
  assert.equal(report(records).rows[0].toolCallId, action.toolCallId);
  assert.ok(readFileSync(path, "utf8").endsWith("\n"));
});
test("config inválida rechazada", () => {
  for (const c of [
    { mode: "oops" },
    { deadlineMs: 0 },
    { maxInputBytes: Infinity },
    { storageRoot: "relative" },
    { calibration: [{ pattern: "x" }] },
  ])
    assert.throws(() => validateConfig(c));
});

test("aclaración tras resume no reemplaza silenciosamente el objetivo completo", async (t) => {
  const f = setup(t);
  f.reviewer.reset(true);
  f.reviewer.state.input("Además, hazlo breve.");
  assert.equal((await f.reviewer.review(action, f.root)).action, "abstain");
  f.reviewer.state.startTask(
    "Objetivo completo: corregir sin añadir dependencias.",
  );
  assert.equal((await f.reviewer.review(action, f.root)).action, "block");
});
test("presupuesto de tokens detiene nuevas consultas entre respuestas", async (t) => {
  const f = setup(t, { maxRemoteTokens: 10, mode: "observe" });
  await f.reviewer.review(action, f.root);
  assert.equal(
    (await f.reviewer.review(action, f.root)).reason,
    "budget_exhausted",
  );
  assert.equal(f.calls(), 1);
});
test("juicio útil o incierto no bloquea", async (t) => {
  for (const choice of ["useful", "uncertain"] as const) {
    const response = structuredClone(conflict);
    response.judgments[0].choice = choice;
    const f = setup(t, {}, async () => response);
    assert.equal((await f.reviewer.review(action, f.root)).action, "allow");
  }
});

test("campos no autorizados tampoco se recuperan indirectamente desde evidencia", async (t) => {
  const f = setup(t);
  const a = {
    ...readAction(),
    input: { path: "a.txt", unexpected: "secret-synthetic" },
  };
  assert.equal((await f.reviewer.review(a, f.root)).action, "abstain");
  f.reviewer.state.before(a, f.root);
  f.reviewer.state.result(
    a,
    [{ type: "text", text: "Texto autorizado" }],
    false,
    {},
  );
  const s = f.reviewer.state.snapshot(readAction("next"), f.root);
  assert.ok(!JSON.stringify(s).includes("secret-synthetic"));
});
