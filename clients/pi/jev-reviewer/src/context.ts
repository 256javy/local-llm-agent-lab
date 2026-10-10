import { spawnSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { basename, isAbsolute, relative, resolve } from "node:path";
import type { Action, Config } from "./contracts.ts";
import { parseShell, SafetyGuard } from "./safety.ts";
import { scopedPath } from "./state.ts";

// Local facts about the action's blast radius, computed by the harness (no network):
// git status of the paths it touches, the scripts it would run and local guard signals.
// Only counts, statuses and paths already present in the action leave the machine;
// file contents are included only for paths inside the authorized scope.
export interface PathFacts {
  path: string;
  exists: boolean;
  dir?: boolean;
  tracked?: number;
  modified?: number;
  untracked?: number;
  ignored?: number;
  createdByAgent?: boolean;
  kind?: "test" | "secret";
}
export interface ExecutedScript {
  path: string;
  via: string;
  content?: string;
  omitted?: string;
}
export interface ActionContext {
  workspace: { git: boolean; modified?: number; staged?: number; untracked?: number };
  paths: PathFacts[];
  executes: ExecutedScript[];
  signals: string[];
  recent: { tool: string; target: string; failed: boolean }[];
  touchesTests: boolean;
}

const testPath =
  /(^|\/)(tests?|__tests__|specs?|__snapshots__|fixtures?|snapshots?)(\/|$)|\.(test|spec)\.[cm]?[jt]sx?$|(^|\/)tests?\.[cm]?[jt]s$|\.snap$|(^|\/)[^/]*(expected|golden)[^/]*$/i;
const secretPath = /(^|\/)\.env(\.|$)|(credential|secret|token|\.pem$|\.key$)/i;
const updateFlag = /(^|\s)(-u|--update[\w-]*|--snapshot-update|--ci=false)(\s|=|$)|\bUPDATE_SNAPSHOTS?=/;
const writes = /(?<![<&\d>])>{1,2}(?!&|\s*\/dev\/)|\bsed\s+(-\w*\s+)*-i|\bperl\s+-\w*i|\b(cp|mv|rm|tee|truncate|unlink)\s|\bgit\s+(checkout|restore|rm|stash)\b/;
const interpreters = ["node", "python", "python3", "ruby", "perl", "deno", "bun", "tsx", "ts-node"];
const shells = ["sh", "bash", "zsh", "dash", "ksh", "source", "."];
const maxScriptBytes = 6000;

function git(cwd: string, args: string[]): string | undefined {
  const r = spawnSync("git", args, { cwd, encoding: "utf8", timeout: 2000 });
  return r.status === 0 ? r.stdout : undefined;
}

export function isTestPath(rel: string): boolean {
  return testPath.test(rel);
}

/** Paths mentioned by the action that resolve inside the workspace (max 10). */
function mentioned(action: Action, cwd: string): string[] {
  const out = new Set<string>();
  const add = (dir: string, raw: string) => {
    if (!raw || raw.includes("$") || raw.startsWith("-") || /[*?[]/.test(raw)) return;
    const p = resolve(dir, raw);
    const rel = relative(cwd, p);
    if (rel.startsWith("..") || isAbsolute(rel)) return;
    if (rel === "" && raw !== ".") return;
    out.add(rel || ".");
  };
  if (typeof action.input.path === "string") add(cwd, action.input.path);
  if (action.toolName === "bash" && typeof action.input.command === "string") {
    let dir = cwd;
    for (const cmd of parseShell(action.input.command)) {
      const [name, ...args] = cmd.words;
      if (name === "cd" && args[0]) {
        dir = resolve(dir, args[0]);
        continue;
      }
      // Only path-like operands: avoids treating every word as a file.
      for (const a of args) if (a === "." || a.includes("/") || a.includes(".") || existsRel(dir, a)) add(dir, a);
      for (const r of cmd.redirects) add(dir, r);
    }
  }
  return [...out].slice(0, 10);
}
function existsRel(dir: string, raw: string): boolean {
  try {
    statSync(resolve(dir, raw));
    return true;
  } catch {
    return false;
  }
}

function pathFacts(cwd: string, rel: string, repo: boolean, agentFiles: ReadonlySet<string>): PathFacts {
  const abs = resolve(cwd, rel);
  const facts: PathFacts = { path: rel, exists: existsRel(cwd, rel) };
  if (facts.exists) facts.dir = statSync(abs).isDirectory();
  if (isTestPath(rel)) facts.kind = "test";
  else if (secretPath.test(rel)) facts.kind = "secret";
  if (agentFiles.has(abs)) facts.createdByAgent = true;
  if (repo && facts.exists) {
    const tracked = git(cwd, ["ls-files", "-z", "--", rel]);
    const status = git(cwd, ["status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=all", "--", rel]);
    if (tracked !== undefined) facts.tracked = tracked.split("\0").filter(Boolean).length;
    if (status !== undefined) {
      const entries = status.split("\0").filter((e) => /^[ MADRCU?!]{2} /.test(e));
      facts.modified = entries.filter((e) => !e.startsWith("??") && !e.startsWith("!!")).length;
      facts.untracked = entries.filter((e) => e.startsWith("??")).length;
      facts.ignored = entries.filter((e) => e.startsWith("!!")).length;
    }
  }
  return facts;
}

/** Scripts the shell command would run: shell files, interpreted files, ./x and npm scripts. */
function executed(command: string, cwd: string, depth = 0): { path: string; via: string; body?: string }[] {
  const out: { path: string; via: string; body?: string }[] = [];
  if (depth > 1) return out;
  let dir = cwd;
  for (const cmd of parseShell(command)) {
    const words = cmd.words.filter((w) => !/^[A-Za-z_][A-Za-z0-9_]*=/.test(w));
    const [name, ...args] = words;
    if (!name) continue;
    if (name === "cd" && args[0]) {
      dir = resolve(dir, args[0]);
      continue;
    }
    const base = basename(name);
    const file = args.find((a) => !a.startsWith("-"));
    if ((shells.includes(base) || interpreters.includes(base)) && file && !args.includes("-c") && !args.includes("-e"))
      out.push({ path: relative(cwd, resolve(dir, file)), via: base });
    else if (name.includes("/") && !isAbsolute(name)) out.push({ path: relative(cwd, resolve(dir, name)), via: "exec" });
    else if (["npm", "pnpm", "yarn"].includes(base)) {
      const run = args[0] === "run" || args[0] === "run-script" ? args[1] : ["test", "start", "build"].includes(args[0]) ? args[0] : undefined;
      if (!run) continue;
      try {
        const body = JSON.parse(readFileSync(resolve(dir, "package.json"), "utf8"))?.scripts?.[run];
        if (typeof body === "string") {
          out.push({ path: relative(cwd, resolve(dir, "package.json")), via: `${base} run ${run}`, body });
          out.push(...executed(body, dir, depth + 1));
        }
      } catch {
        // No package.json: nothing to describe.
      }
    }
  }
  return out;
}

export function buildContext(
  action: Action,
  cwd: string,
  config: Config,
  agentFiles: ReadonlySet<string>,
  recent: ActionContext["recent"],
): ActionContext {
  const top = git(cwd, ["rev-parse", "--show-toplevel"]);
  const repo = top !== undefined;
  const workspace: ActionContext["workspace"] = { git: repo };
  if (repo) {
    const status = git(cwd, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]) ?? "";
    const entries = status.split("\0").filter((e) => /^[ MADRCU?!]{2} /.test(e));
    workspace.untracked = entries.filter((e) => e.startsWith("??")).length;
    workspace.staged = entries.filter((e) => !e.startsWith("??") && e[0] !== " ").length;
    workspace.modified = entries.filter((e) => !e.startsWith("??") && e[1] !== " ").length;
  }
  const executes: ExecutedScript[] = [];
  let bytes = 0;
  if (action.toolName === "bash" && typeof action.input.command === "string")
    for (const e of executed(action.input.command, cwd).slice(0, 4)) {
      const script: ExecutedScript = { path: e.path, via: e.via };
      if (e.body !== undefined) script.content = e.body;
      else if (!scopedPath(config, cwd, e.path)) script.omitted = "fuera del alcance autorizado";
      else
        try {
          const text = readFileSync(resolve(cwd, e.path), "utf8");
          if (Buffer.byteLength(text) + bytes > maxScriptBytes) script.omitted = "demasiado grande";
          else {
            script.content = text;
            bytes += Buffer.byteLength(text);
          }
        } catch {
          script.omitted = "no existe o no es legible";
        }
      executes.push(script);
    }
  const paths = [...new Set([...mentioned(action, cwd), ...executes.map((e) => e.path)])]
    .slice(0, 10)
    .map((rel) => pathFacts(cwd, rel, repo, agentFiles));
  let signals: string[] = [];
  try {
    signals = new SafetyGuard(resolve(cwd), config.protectedPaths, agentFiles)
      .assess(action)
      .map((f) => `${f.verdict}:${f.rule}`);
  } catch {
    signals = ["ask:safety_error"];
  }
  const command = typeof action.input.command === "string" ? action.input.command : "";
  // Reading or running tests is normal; only writes to tests or snapshot updates are asked about.
  const touchesTests =
    action.toolName === "bash"
      ? updateFlag.test(command) || (writes.test(command) && paths.some((p) => p.kind === "test"))
      : paths.some((p) => p.kind === "test");
  return { workspace, paths, executes, signals, recent: recent.slice(-6), touchesTests };
}
