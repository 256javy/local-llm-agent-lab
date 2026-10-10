import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Requirement } from "./contracts.ts";

// pi-agent-bench task loading, workspace preparation and verification (shared by bench and replay).
export interface Task {
  id: string;
  category: string;
  prompt: string;
  requirements: Requirement[];
  git?: boolean;
  uncommitted?: Record<string, string>;
  expectedMaxToolCalls?: number;
  scopePaths: string[];
  dir: string;
}
export interface Verify {
  pass: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
}
// Checks that measure harm (lost or modified data) rather than task success.
export const damageCheck = /intact|conservad|presente|no se ejecut|no borr|no modific|sin /i;

export function loadTasks(benchRoot: string, only?: string[]): Task[] {
  return readdirSync(join(benchRoot, "tasks"))
    .sort()
    .filter((id) => !only || only.includes(id))
    .map((id) => {
      const dir = join(benchRoot, "tasks", id);
      return { ...(JSON.parse(readFileSync(join(dir, "task.json"), "utf8")) as Omit<Task, "dir">), dir };
    });
}
function git(cwd: string, ...args: string[]) {
  const r = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (r.status !== 0) throw new Error(`git ${args.join(" ")} (${r.status ?? r.signal}): ${r.stderr}${r.stdout}`);
}
export function prepare(task: Task, root: string) {
  // cpSync preserves file modes, which the permissions task depends on.
  cpSync(join(task.dir, "workspace"), root, { recursive: true });
  if (task.git) {
    git(root, "init", "-q", "-b", "main");
    git(root, "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "add", "-A");
    git(root, "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "commit", "-q", "-m", "inicial");
  }
  for (const [rel, text] of Object.entries(task.uncommitted ?? {})) {
    mkdirSync(dirname(join(root, rel)), { recursive: true });
    writeFileSync(join(root, rel), text);
  }
}
export function verify(task: Task, root: string): Verify {
  // verify.cjs reads its originals from its own directory: run it in place, outside the sandbox.
  const check = spawnSync(process.execPath, [join(task.dir, "verify.cjs"), root], {
    cwd: task.dir,
    encoding: "utf8",
    timeout: 20000,
  });
  try {
    return JSON.parse(check.stdout.trim().split("\n").at(-1) ?? "");
  } catch {
    return { pass: false, checks: [{ name: "verify", ok: false, detail: check.stderr.slice(-300) }] };
  }
}
