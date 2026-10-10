import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, statSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { readRecords } from "../src/report.ts";

type Call = { name: string; arguments: unknown } | undefined;

/** Runs real Pi against a scripted model; `next(n)` returns the n-th tool call or undefined to finish. */
async function runPi(t: TestContext, config: Record<string, unknown>, next: (n: number) => Call) {
  const root = mkdtempSync(join(tmpdir(), "jev-guard-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cwd = join(root, "work");
  const agent = join(root, "agent");
  mkdirSync(cwd);
  mkdirSync(agent);
  writeFileSync(join(cwd, "a.txt"), "x\n", { mode: 0o644 });
  const bodies: string[] = [];
  const server = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    bodies.push(body);
    const n = bodies.length;
    const call = next(n);
    res.writeHead(200, { "content-type": "text/event-stream" });
    const chunk = (delta: unknown, finish_reason: string | null) =>
      `data: ${JSON.stringify({ id: `chat_${n}`, object: "chat.completion.chunk", created: 1, model: "fixture", choices: [{ index: 0, delta, finish_reason }] })}\n\n`;
    res.write(
      chunk(
        call
          ? {
              role: "assistant",
              tool_calls: [{ index: 0, id: `call_${n}`, type: "function", function: { name: call.name, arguments: JSON.stringify(call.arguments) } }],
            }
          : { role: "assistant", content: "Hecho." },
        null,
      ),
    );
    res.write(chunk({}, call ? "tool_calls" : "stop"));
    res.end("data: [DONE]\n\n");
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  t.after(() => {
    server.closeAllConnections();
    server.close();
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  writeFileSync(
    join(agent, "models.json"),
    JSON.stringify({
      providers: {
        fixture: {
          baseUrl: `http://127.0.0.1:${address.port}/v1`,
          api: "openai-completions",
          apiKey: "synthetic",
          models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
        },
      },
    }),
  );
  const configPath = join(root, "config.json");
  writeFileSync(configPath, JSON.stringify({ storageRoot: join(root, "reviews"), ...config }));
  const cli = fileURLToPath(new URL("../node_modules/@earendil-works/pi-coding-agent/dist/cli.js", import.meta.url));
  const extension = fileURLToPath(new URL("../src/index.ts", import.meta.url));
  const child = spawn(
    process.execPath,
    [cli, "--no-extensions", "--no-skills", "--no-prompt-templates", "-e", extension, "--jev-config", configPath,
      "--provider", "fixture", "--model", "fixture", "--thinking", "off", "--mode", "json",
      "--session", join(root, "session.jsonl"), "-p", "Tarea sintética."],
    {
      cwd,
      env: { ...process.env, PI_CODING_AGENT_DIR: agent, JEV_MODE: "", JEV_REVIEWER: "", JEV_SAFETY: "", TYPESAFE_API_KEY: "" },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  child.stdout.on("data", (c) => (output += c));
  child.stderr.on("data", (c) => (output += c));
  t.after(() => child.kill());
  const code = await new Promise<number | null>((r) => child.on("close", r));
  const sessionDir = join(root, "reviews", readdirSync(join(root, "reviews"))[0]);
  const records = readRecords(join(sessionDir, readdirSync(sessionDir)[0], "events.jsonl"));
  return { code, output, bodies, records, cwd };
}

test("Pi real: un edit inválido repetido recibe la pista y la ejecución se aborta", { timeout: 30000 }, async (t) => {
  const { bodies, records, output } = await runPi(
    t,
    { mode: "enforce", reviewer: "local", maxIdenticalFailures: 3 },
    // Missing `path`: rejected by Pi's argument validation, before tool_call.
    () => ({ name: "edit", arguments: { edits: [{ oldText: "x", newText: "y" }] } }),
  );
  assert.ok(bodies.length >= 3 && bodies.length <= 4, `solicitudes: ${bodies.length}\n${output}`);
  assert.ok(!bodies[1].includes("[Jev]"), "el primer fallo no lleva pista");
  assert.ok(bodies[2].includes("intento id\\u00e9ntico n\\u00famero 2") || bodies[2].includes("intento idéntico número 2"));
  const loops = records.filter((r) => r.kind === "loop");
  assert.deepEqual(loops.map((r) => r.action), ["hint", "abort"]);
});

test("Pi real: la guardia de seguridad bloquea con el revisor de utilidad apagado y el comando no se ejecuta", { timeout: 30000 }, async (t) => {
  const { code, bodies, records, cwd, output } = await runPi(t, { mode: "off", reviewer: "off" }, (n) =>
    n === 1 ? { name: "bash", arguments: { command: "chmod 777 a.txt" } } : undefined,
  );
  assert.equal(code, 0, output);
  assert.equal(statSync(join(cwd, "a.txt")).mode & 0o777, 0o644);
  assert.ok(bodies[1].includes("permissions_world_writable"));
  assert.ok(bodies[1].includes("chmod +x"), "incluye una alternativa concreta");
  const d = records.find((r) => r.kind === "decision") as { action: string; safety: { rule: string } };
  assert.equal(d.action, "block");
  assert.equal(d.safety.rule, "permissions_world_writable");
});
