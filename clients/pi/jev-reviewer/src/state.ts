import { realpathSync, readFileSync, statSync } from "node:fs";
import { parseShell } from "./safety.ts";
import { dirname, relative, resolve, basename } from "node:path";
import {
  hash,
  type Action,
  type Config,
  type Evidence,
  type Snapshot,
} from "./contracts.ts";

export function scopedPath(
  config: Config,
  cwd: string,
  path: unknown,
): string | undefined {
  if (!config.scope || typeof path !== "string") return;
  try {
    const root = realpathSync(config.scope.root);
    if (realpathSync(cwd) !== root) return;
    const target = resolve(cwd, path);
    const rel = relative(root, target);
    if (
      !rel ||
      rel.startsWith("..") ||
      !config.scope.paths.includes(rel) ||
      rel
        .split("/")
        .some(
          (p) => p.startsWith(".") || /(?:credential|secret|token)/i.test(p),
        )
    )
      return;
    let actual: string;
    try {
      actual = realpathSync(target);
    } catch {
      actual = resolve(realpathSync(dirname(target)), basename(target));
    }
    if (actual !== target || relative(root, actual).startsWith("..")) return;
    return target;
  } catch {
    return;
  }
}
export function fingerprint(path: string, limit: number): string | undefined {
  try {
    if (!statSync(path).isFile() || statSync(path).size > limit) return;
    return hash(readFileSync(path).toString("base64"));
  } catch {
    return;
  }
}
export class State {
  revision = 0;
  taskVersion = 0;
  objective: string[] = [];
  incompleteHistory = false;
  evidence: Evidence[] = [];
  pending = new Map<
    string,
    {
      action: Action;
      cwd: string;
      mutationsBefore: number;
      fingerprint?: string;
      path?: string;
    }
  >();
  // Last run of each shell command (cwd+command): outcome, consecutive identical runs and
  // the mutation count right after it, to tell whether anything changed since.
  runs = new Map<
    string,
    { toolCallId: string; mutations: number; failed: boolean; streak: number }
  >();
  mutations = 0;
  // Files whose content the agent observed or produced in this session (absolute paths).
  known = new Set<string>();
  // Files the agent created or rewrote with `write` (absolute paths).
  written = new Set<string>();
  // Recent mutating actions and their outcome (no output): bash commands and scoped paths.
  recent: { tool: string; target: string; failed: boolean }[] = [];
  sessionId = "unknown";
  branchId = "unknown";
  constructor(readonly config: Config) {}
  invalidate(clearObjective = false) {
    this.revision++;
    this.evidence = [];
    this.pending.clear();
    this.runs.clear();
    if (clearObjective) {
      this.known.clear();
      this.written.clear();
      this.recent = [];
      this.objective = [];
      this.incompleteHistory = true;
      this.taskVersion++;
    }
  }
  startTask(text: string) {
    this.objective = [];
    this.incompleteHistory = false;
    this.input(text);
  }
  input(text: string) {
    this.invalidate();
    this.objective.push(text);
    this.taskVersion++;
  }
  before(action: Action, cwd: string) {
    const path = scopedPath(this.config, cwd, action.input.path);
    const fp = path ? fingerprint(path, this.config.maxInputBytes) : undefined;
    this.pending.set(action.toolCallId, {
      action: structuredClone(action),
      cwd,
      mutationsBefore: this.mutations,
      path,
      fingerprint: fp,
    });
    // Arbitrary shell can mutate any file; no shell text is classified as read-only.
    if (["bash", "edit", "write"].includes(action.toolName)) {
      this.evidence = [];
      this.revision++;
      this.mutations++;
    }
  }
  private commandKey(action: Action, cwd: string) {
    return hash({ cwd, command: action.input.command });
  }
  /** Relative path of an existing, non-empty file that `write` would replace unseen. */
  blindOverwrite(action: Action, cwd: string): string | undefined {
    if (action.toolName !== "write" || typeof action.input.path !== "string")
      return;
    const target = resolve(cwd, action.input.path);
    try {
      const stat = statSync(target);
      if (!stat.isFile() || stat.size === 0 || this.known.has(target)) return;
    } catch {
      return;
    }
    return relative(cwd, target) || action.input.path;
  }
  private observe(action: Action, cwd: string) {
    const input = action.input;
    if (["read", "write", "edit"].includes(action.toolName) && typeof input.path === "string")
      this.known.add(resolve(cwd, input.path));
    if (action.toolName === "write" && typeof input.path === "string")
      this.written.add(resolve(cwd, input.path));
    if (action.toolName === "bash" && typeof input.command === "string") {
      let dir = cwd;
      for (const cmd of parseShell(input.command)) {
        const [name, ...args] = cmd.words;
        if (name === "cd" && args[0]) dir = resolve(dir, args[0]);
        if (["cat", "head", "tail", "nl", "less", "more", "bat"].includes(name ?? ""))
          for (const a of args) if (!a.startsWith("-")) this.known.add(resolve(dir, a));
      }
    }
  }
  /**
   * The same command proposed again with nothing executed since: after a failure, or after
   * two identical successful runs in a row (one retry is tolerated for flaky checks and polling).
   */
  repeatedRun(
    action: Action,
    cwd: string,
  ): { pattern: "repeated_failed_command" | "repeated_command"; toolCallId: string } | undefined {
    if (action.toolName !== "bash" || typeof action.input.command !== "string")
      return;
    const prior = this.runs.get(this.commandKey(action, cwd));
    if (!prior || prior.mutations !== this.mutations) return;
    if (prior.failed)
      return { pattern: "repeated_failed_command", toolCallId: prior.toolCallId };
    if (prior.streak >= 2)
      return { pattern: "repeated_command", toolCallId: prior.toolCallId };
  }
  result(action: Action, content: unknown, isError: boolean, details: unknown) {
    const prior = this.pending.get(action.toolCallId);
    if (!prior) return; // Bloqueos no ejecutados no cambian el estado.
    this.pending.delete(action.toolCallId);
    this.revision++;
    if (!isError) this.observe(prior.action, prior.cwd);
    if (["bash", "edit", "write"].includes(action.toolName)) {
      const input = prior.action.input;
      const target =
        action.toolName === "bash"
          ? this.config.scope?.allowBash ? String(input.command) : "(comando no autorizado)"
          : scopedPath(this.config, prior.cwd, input.path)
            ? String(input.path)
            : "(ruta fuera del alcance)";
      this.recent = [...this.recent, { tool: action.toolName, target, failed: isError }].slice(-6);
    }
    if (action.toolName === "bash" && typeof prior.action.input.command === "string") {
      const key = hash({ cwd: prior.cwd, command: prior.action.input.command });
      const last = this.runs.get(key);
      const chained =
        last && last.mutations === prior.mutationsBefore && last.failed === isError;
      this.runs.set(key, {
        toolCallId: action.toolCallId,
        mutations: this.mutations,
        failed: isError,
        streak: chained ? last.streak + 1 : 1,
      });
    }
    if (
      action.toolName !== "read" ||
      !prior?.path ||
      !prior.fingerprint ||
      isError ||
      (details && JSON.stringify(details).includes("truncat"))
    )
      return;
    const fp = fingerprint(prior.path, this.config.maxInputBytes);
    if (fp !== prior.fingerprint || !Array.isArray(content)) return;
    const text = content
      .filter((x) => x?.type === "text" && typeof x.text === "string")
      .map((x) => x.text)
      .join("\n");
    if (!text || Buffer.byteLength(text) > this.config.maxInputBytes / 2)
      return;
    this.evidence.push({
      id: action.toolCallId,
      path: prior.path,
      fingerprint: fp!,
      input: Object.fromEntries(
        Object.entries(prior.action.input).filter(([key]) =>
          ["path", "offset", "limit"].includes(key),
        ),
      ),
      text,
      available: true,
    });
    this.evidence = this.evidence.slice(-8);
  }
  snapshot(action: Action, cwd: string): Snapshot {
    const evidence = this.evidence.filter(
      (e) =>
        e.available &&
        scopedPath(this.config, cwd, e.path) &&
        fingerprint(e.path, this.config.maxInputBytes) === e.fingerprint,
    );
    return structuredClone({
      schemaVersion: 1,
      sessionId: this.sessionId,
      branchId: this.branchId,
      taskVersion: this.taskVersion,
      stateRevision: this.revision,
      cwd,
      objective: this.objective,
      requirements: this.config.requirements,
      action,
      evidence,
      pending: [...this.pending.keys()],
      omissions: [
        ...(this.objective.length ? [] : ["objective"]),
        ...(this.incompleteHistory ? ["prior_task_context"] : []),
      ],
    });
  }
}
