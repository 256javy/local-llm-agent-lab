import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildContext, isTestPath } from "../src/context.ts";
import { validateConfig } from "../src/config.ts";
import { questionsFor } from "../src/questions.ts";
import { Reviewer } from "../src/reviewer.ts";
import type { Action, Config, ReviewResponse, Snapshot } from "../src/contracts.ts";

function repo(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), "jev-context-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "test"));
  mkdirSync(join(root, "notes"));
  mkdirSync(join(root, "scripts"));
  writeFileSync(join(root, "test.cjs"), "// node test.cjs --update reescribe test/expected.json\n");
  writeFileSync(join(root, "test/expected.json"), "{}\n");
  writeFileSync(join(root, "scripts/deploy.sh"), 'rm -rf "./$DIR"/*\n');
  writeFileSync(join(root, "src.js"), "module.exports = 1;\n");
  const git = (...args: string[]) => spawnSync("git", args, { cwd: root });
  git("init", "-q");
  git("add", "-A");
  git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init");
  writeFileSync(join(root, "src.js"), "module.exports = 2;\n");
  writeFileSync(join(root, "notes/clientes.md"), "trabajo sin versionar\n");
  const config = validateConfig({
    scope: {
      root,
      paths: ["test.cjs", "test/expected.json", "scripts/deploy.sh", "src.js"],
      allowBash: true,
      authorization: "Prueba sintética.",
    },
  });
  return { root, config };
}
const bash = (command: string): Action => ({ toolCallId: "c", toolName: "bash", input: { command } });

test("contexto: estado git por ruta, scripts ejecutados en alcance y señales locales sin detalles", (t) => {
  const { root, config } = repo(t);
  const del = buildContext(bash("rm -rf notes src.js"), root, config, new Set(), []);
  assert.deepEqual(del.workspace, { git: true, untracked: 1, staged: 0, modified: 1 });
  const notes = del.paths.find((p) => p.path === "notes")!;
  assert.equal(notes.untracked, 1);
  assert.equal(notes.tracked, 0);
  assert.equal(del.paths.find((p) => p.path === "src.js")!.modified, 1);
  assert.ok(del.signals.every((s) => /^(ask|block):[a-z_]+$/.test(s)), "solo reglas, sin rutas");
  const run = buildContext(bash("bash scripts/deploy.sh"), root, config, new Set(), []);
  assert.equal(run.executes[0].content, 'rm -rf "./$DIR"/*\n');
  assert.ok(run.signals.includes("block:delete_unresolved_target"));
  writeFileSync(join(root, "other.sh"), "echo secreto\n");
  const out = buildContext(bash("sh other.sh"), root, config, new Set(), []);
  assert.equal(out.executes[0].content, undefined);
  assert.equal(out.executes[0].omitted, "fuera del alcance autorizado");
});

test("contexto: solo escribir tests o regenerar snapshots activa test_tampering; leerlos o ejecutarlos no", (t) => {
  const { root, config } = repo(t);
  const touches = (a: Action) => buildContext(a, root, config, new Set(), []).touchesTests;
  assert.equal(touches(bash("node test.cjs")), false);
  assert.equal(touches(bash("node test.cjs 2>&1")), false);
  assert.equal(touches(bash("cat test/expected.json")), false);
  assert.equal(touches(bash("node test.cjs --update")), true);
  assert.equal(touches(bash("node src.js > test/expected.json")), true);
  assert.equal(touches(bash("sed -i 's/1/2/' test.cjs")), true);
  assert.equal(touches({ toolCallId: "e", toolName: "edit", input: { path: "test/expected.json", edits: [] } }), true);
  assert.equal(touches({ toolCallId: "e", toolName: "edit", input: { path: "src.js", edits: [] } }), false);
  assert.ok(isTestPath("src/__tests__/a.ts") && isTestPath("a.spec.js") && isTestPath("__snapshots__/x.snap"));
  assert.ok(!isTestPath("src/contest.js") && !isTestPath("src/latest.js"));
});

test("questionsFor añade test_tampering solo con touchesTests y el contexto entra en las instrucciones", () => {
  const s = {
    schemaVersion: 1, sessionId: "s", branchId: "b", taskVersion: 1, stateRevision: 1, cwd: "/w",
    objective: ["Haz que pase."], requirements: [], evidence: [], pending: [], omissions: [],
    action: bash("node test.cjs --update"),
  } as Snapshot;
  assert.deepEqual(Object.values(questionsFor(s).references).map((r) => r.pattern), ["off_task_action", "unsafe_action"]);
  const withContext = {
    ...s,
    context: { workspace: { git: false }, paths: [], executes: [], signals: [], recent: [], touchesTests: true },
  };
  const q = questionsFor(withContext);
  assert.deepEqual(Object.values(q.references).map((r) => r.pattern), ["off_task_action", "unsafe_action", "test_tampering"]);
  assert.ok(JSON.stringify(q.questions).includes("state.context"));
});

test("brazo jev: contexto en el snapshot y bloqueo test_tampering calibrado", async (t) => {
  const { root, config: base } = repo(t);
  const config: Config = {
    ...base,
    mode: "enforce",
    reviewer: "jev",
    calibration: [{ pattern: "test_tampering", tool: "bash", threshold: 0.8, reference: "test-only" }],
  };
  const seen: Snapshot[] = [];
  const answer: ReviewResponse = {
    model: "mock",
    usage: { input_tokens: 1, output_tokens: 1 },
    judgments: [
      { pattern: "test_tampering", reference: "action", choice: "problem", confidence: 0.9, probabilities: { problem: 0.9, useful: 0.05, uncertain: 0.05 } },
    ],
  };
  const reviewer = new Reviewer(config, async (s) => (seen.push(s), structuredClone(answer)), () => {});
  reviewer.state.input("Haz que pase el test.");
  const first = await reviewer.review(bash("node test.cjs --update"), root);
  assert.equal(first.action, "block");
  assert.equal(first.pattern, "test_tampering");
  assert.ok(first.reason.includes("corrige el código bajo prueba"));
  assert.equal(seen[0].context?.touchesTests, true);
  const retry = await reviewer.review(bash("node test.cjs --update"), root);
  assert.equal(retry.action, "block", "el reintento idéntico no se salta");
  assert.equal(seen.length, 1);
  // Local and off arms never compute context.
  const local = new Reviewer({ ...config, reviewer: "local" }, async () => assert.fail("sin red"), () => {});
  local.state.input("x");
  assert.equal((await local.review(bash("node test.cjs --update"), root)).snapshot.context, undefined);
});

test("los bloqueos de eficiencia no agotan el presupuesto de test_tampering", async (t) => {
  const { root, config: base } = repo(t);
  const config: Config = {
    ...base,
    mode: "enforce",
    reviewer: "jev",
    maxBlocksPerTask: 1,
    calibration: [{ pattern: "test_tampering", tool: "bash", threshold: 0.8, reference: "test-only" }],
  };
  const answer: ReviewResponse = {
    model: "mock",
    usage: { input_tokens: 1, output_tokens: 1 },
    judgments: [
      { pattern: "test_tampering", reference: "action", choice: "problem", confidence: 0.9, probabilities: { problem: 0.9, useful: 0.05, uncertain: 0.05 } },
    ],
  };
  const reviewer = new Reviewer(config, async () => structuredClone(answer), () => {});
  reviewer.state.input("Haz que pase el test.");
  reviewer.blocks = 1; // Efficiency budget already spent.
  const d = await reviewer.review(bash("node test.cjs --update"), root);
  assert.equal(d.action, "block");
  assert.equal(reviewer.guardBlocks, 1);
  const other = await reviewer.review(bash("node test.cjs -u"), root);
  assert.equal(other.action, "allow", "ambos presupuestos agotados para una acción nueva");
});

test("una acción idéntica ya juzgada como test_tampering sigue bloqueada sin consultar ni gastar presupuesto", async (t) => {
  const { root, config: base } = repo(t);
  const config: Config = {
    ...base,
    mode: "enforce",
    reviewer: "jev",
    maxBlocksPerTask: 1,
    calibration: [{ pattern: "test_tampering", tool: "bash", threshold: 0.8, reference: "test-only" }],
  };
  let calls = 0;
  const answer: ReviewResponse = {
    model: "mock",
    usage: { input_tokens: 1, output_tokens: 1 },
    judgments: [
      { pattern: "test_tampering", reference: "action", choice: "problem", confidence: 0.9, probabilities: { problem: 0.9, useful: 0.05, uncertain: 0.05 } },
    ],
  };
  const reviewer = new Reviewer(config, async () => (calls++, structuredClone(answer)), () => {});
  reviewer.state.input("Haz que pase el test.");
  const first = await reviewer.review(bash("node test.cjs --update"), root);
  assert.equal(first.action, "block");
  for (let i = 0; i < 3; i++) {
    const again = await reviewer.review(bash("node test.cjs --update"), root);
    assert.equal(again.action, "block");
    assert.ok(again.reason.includes("no la repitas"));
  }
  assert.equal(calls, 1);
  assert.equal(reviewer.guardBlocks, 1);
  // An explicit allow-once lifts it; a new user message starts a new task.
  const blocked = await reviewer.review(bash("node test.cjs --update"), root);
  assert.ok(reviewer.allowOnce(blocked.reviewId));
  assert.equal((await reviewer.review(bash("node test.cjs --update"), root)).action, "allow");
  reviewer.state.input("Sí, actualiza el snapshot.");
  assert.equal(reviewer.state.taskVersion, 2);
});
