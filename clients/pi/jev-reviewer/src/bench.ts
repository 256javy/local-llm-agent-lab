import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { defaults, validateConfig } from "./config.ts";
import { readRecords, report } from "./report.ts";
import type { Arm, Calibration, Config, Mode } from "./contracts.ts";
import { damageCheck, loadTasks, prepare, verify } from "./bench-tasks.ts";

// Runs pi-agent-bench tasks through Pi with each reviewer variant, inside bubblewrap.
const { values } = parseArgs({
  options: {
    bench: { type: "string", default: join(homedir(), "projects/pi-agent-bench") },
    tasks: { type: "string" },
    variants: { type: "string", default: "baseline,safety,local,jev" },
    repetitions: { type: "string", default: "1" },
    model: { type: "string" },
    provider: { type: "string" },
    profile: { type: "string" },
    "authorize-synthetic-api": { type: "boolean", default: false },
    policy: { type: "string" },
    output: { type: "string" },
    timeout: { type: "string", default: "240" },
  },
});

const variants: Record<string, { reviewer: Arm; mode: Mode; safety: Mode }> = {
  // Baseline observes safety so the report shows what would have been blocked.
  baseline: { reviewer: "off", mode: "off", safety: "observe" },
  safety: { reviewer: "off", mode: "off", safety: "enforce" },
  local: { reviewer: "local", mode: "enforce", safety: "enforce" },
  jev: { reviewer: "jev", mode: "enforce", safety: "enforce" },
};
const selected = values.variants!.split(",");
if (selected.some((v) => !variants[v])) throw new Error("Variante inválida.");
if (!values.model || !values.provider || !values.profile)
  throw new Error("Se requieren --provider, --model y --profile explícitos.");
if (selected.includes("jev") && (!values["authorize-synthetic-api"] || !process.env.TYPESAFE_API_KEY))
  throw new Error("La variante jev requiere --authorize-synthetic-api y TYPESAFE_API_KEY.");
const repetitions = Number(values.repetitions);
if (!Number.isSafeInteger(repetitions) || repetitions < 1 || repetitions > 20)
  throw new Error("Repeticiones inválidas.");
if (spawnSync("bwrap", ["--version"]).status !== 0)
  throw new Error("Se requiere bubblewrap: el banco ejecuta acciones destructivas a propósito.");

const policyPath =
  values.policy ?? fileURLToPath(new URL("../policies/deterministic.json", import.meta.url));
const policy = JSON.parse(readFileSync(policyPath, "utf8")) as Calibration[];

const benchRoot = resolve(values.bench!);
const tasks = loadTasks(benchRoot, values.tasks?.split(","));
const benchCommit = spawnSync("git", ["-C", benchRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).stdout.trim();

const output = resolve(values.output ?? defaults.storageRoot);
mkdirSync(output, { recursive: true, mode: 0o700 });
const run = mkdtempSync(join(output, "bench-"));
const extension = fileURLToPath(new URL("./index.ts", import.meta.url));
const pi = fileURLToPath(
  new URL("../node_modules/@earendil-works/pi-coding-agent/dist/cli.js", import.meta.url),
);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const userAgentDir = process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi/agent");
writeFileSync(
  join(run, "manifest.json"),
  JSON.stringify(
    {
      schemaVersion: 1,
      bench: benchRoot,
      benchCommit,
      variants: Object.fromEntries(selected.map((v) => [v, variants[v]])),
      repetitions,
      profile: values.profile,
      localModel: values.model,
      provider: values.provider,
      remoteModel: defaults.model,
      remoteModelMutable: true,
      piVersion: "0.85.1",
      sdkVersion: "0.6.0",
      policy,
      policyPath,
      sandbox: "bubblewrap: sistema en solo lectura; workspace y directorio de la ejecución escribibles; red compartida",
      startedAt: new Date().toISOString(),
      limitations: [
        "Piloto pequeño; sin conclusión estadística.",
        "La política determinista no es una calibración empírica de Jev.",
      ],
    },
    null,
    2,
  ),
  { mode: 0o600 },
);

function sessionMetrics(path: string) {
  let toolCalls = 0;
  let toolErrors = 0;
  let input = 0;
  let outputTokens = 0;
  let cacheRead = 0;
  if (!existsSync(path)) return { toolCalls, toolErrors, input, output: outputTokens, cacheRead };
  for (const line of readFileSync(path, "utf8").split("\n").filter(Boolean)) {
    const entry = JSON.parse(line);
    const m = entry.message;
    if (entry.type !== "message" || !m) continue;
    if (m.role === "assistant") {
      toolCalls += (m.content ?? []).filter((c: { type: string }) => c.type === "toolCall").length;
      input += m.usage?.input ?? 0;
      outputTokens += m.usage?.output ?? 0;
      cacheRead += m.usage?.cacheRead ?? 0;
    }
    if (m.role === "toolResult" && m.isError) toolErrors++;
  }
  return { toolCalls, toolErrors, input, output: outputTokens, cacheRead };
}

const rows: Record<string, unknown>[] = [];
for (let repeat = 0; repeat < repetitions; repeat++) {
  for (const task of tasks) {
    const ordered = repeat % 2 ? [...selected].reverse() : selected;
    for (const variant of ordered) {
      const name = `${task.id}-${repeat}-${variant}`;
      const root = join(run, name, "ws");
      mkdirSync(root, { recursive: true, mode: 0o700 });
      prepare(task, root);
      const v = variants[variant];
      const config: Config = validateConfig({
        ...defaults,
        ...v,
        storageRoot: join(run, name, "reviews"),
        requirements: task.requirements,
        scope: {
          root,
          paths: task.scopePaths,
          allowBash: true,
          authorization:
            "Banco sintético pi-agent-bench; objetivo, argumentos y lecturas de rutas enumeradas. Sin resultados bash.",
        },
        calibration: v.reviewer === "off" ? [] : policy,
      });
      const configPath = join(run, name, "config.json");
      writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 });
      const session = join(run, name, "session.jsonl");
      // Private Pi agent dir: the sandbox keeps ~/.pi read-only and user extensions out.
      const agentDir = join(run, name, "agent");
      mkdirSync(agentDir, { mode: 0o700 });
      for (const file of ["models.json", "settings.json"])
        if (existsSync(join(userAgentDir, file))) cpSync(join(userAgentDir, file), join(agentDir, file));
      mkdirSync(join(run, name, "reviews"), { mode: 0o700 });
      const begin = performance.now();
      const child = spawnSync(
        "bwrap",
        [
          "--ro-bind", "/", "/",
          "--dev", "/dev",
          "--proc", "/proc",
          "--tmpfs", "/tmp",
          "--bind", join(run, name), join(run, name),
          "--ro-bind", packageRoot, packageRoot,
          "--die-with-parent",
          "--setenv", "PI_CODING_AGENT_DIR", agentDir,
          "--chdir", root,
          process.execPath,
          pi,
          "--no-extensions",
          "--no-skills",
          "--no-prompt-templates",
          "-e", extension,
          "--jev-config", configPath,
          "--jev-mode", v.mode,
          "--jev-reviewer", v.reviewer,
          "--jev-safety", v.safety,
          "--provider", values.provider!,
          "--model", values.model!,
          "--thinking", "off",
          "--session", session,
          "--mode", "json",
          "-p", task.prompt,
        ],
        {
          encoding: "utf8",
          timeout: Number(values.timeout) * 1000,
          maxBuffer: 32 * 1024 * 1024,
        },
      );
      const elapsedMs = performance.now() - begin;
      writeFileSync(join(run, name, "pi.jsonl"), child.stdout ?? "", { mode: 0o600 });
      writeFileSync(join(run, name, "stderr.txt"), child.stderr ?? "", { mode: 0o600 });
      const verified = verify(task, root);
      const events = readdirSync(join(run, name, "reviews"), { recursive: true })
        .map(String)
        .filter((p) => p.endsWith("events.jsonl"))
        .flatMap((p) => readRecords(join(run, name, "reviews", p)));
      const r = report(events);
      rows.push({
        task: task.id,
        category: task.category,
        variant,
        repeat,
        outcome: verified.pass ? "pass" : "fail",
        failedChecks: verified.checks.filter((c) => !c.ok).map((c) => `${c.name}: ${c.detail}`),
        processExit: child.status,
        timedOut: child.error ? String(child.error) : undefined,
        elapsedMs: Math.round(elapsedMs),
        expectedMaxToolCalls: task.expectedMaxToolCalls,
        ...sessionMetrics(session),
        proposed: r.proposed,
        utilityBlocks: r.blocked - r.safetyBlocked,
        safetyBlocks: r.safetyBlocked,
        safetyFlagged: r.safetyFlagged,
        utilityWouldBlock: r.wouldBlock - r.safetyBlocked,
        remoteResponses: r.remoteResponses,
        reviewerMs: Math.round(r.reviewerMs),
        safetyRules: r.rows.filter((x) => x.safetyRule).map((x) => `${x.action}:${x.safetyRule}`),
        utilityPatterns: r.rows.filter((x) => x.pattern !== "none").map((x) => `${x.action}:${x.pattern}`),
      });
      writeFileSync(join(run, "results.json"), JSON.stringify(rows, null, 2), { mode: 0o600 });
      const last = rows.at(-1)!;
      console.error(
        `${name}: ${last.outcome} ${Math.round(elapsedMs / 1000)}s tools=${last.toolCalls} seg=${last.safetyBlocks} util=${last.utilityBlocks}`,
      );
    }
  }
}

const summary = selected.map((variant) => {
  const rs = rows.filter((r) => r.variant === variant);
  const sum = (k: string) => rs.reduce((a, r) => a + Number(r[k] ?? 0), 0);
  const damaged = rs.filter((r) =>
    (r.failedChecks as string[]).some((c) => damageCheck.test(c)),
  ).length;
  return {
    variant,
    runs: rs.length,
    pass: rs.filter((r) => r.outcome === "pass").length,
    damaged,
    toolCalls: sum("toolCalls"),
    toolErrors: sum("toolErrors"),
    safetyBlocks: sum("safetyBlocks"),
    safetyFlagged: sum("safetyFlagged"),
    utilityBlocks: sum("utilityBlocks"),
    outputTokens: sum("output"),
    elapsedS: Math.round(sum("elapsedMs") / 1000),
  };
});
writeFileSync(join(run, "summary.json"), JSON.stringify(summary, null, 2), { mode: 0o600 });
console.log(JSON.stringify({ directory: run, summary }, null, 2));
