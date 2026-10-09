import { realpathSync, readFileSync, statSync } from "node:fs";
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
    { action: Action; fingerprint?: string; path?: string }
  >();
  sessionId = "unknown";
  branchId = "unknown";
  constructor(readonly config: Config) {}
  invalidate(clearObjective = false) {
    this.revision++;
    this.evidence = [];
    this.pending.clear();
    if (clearObjective) {
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
      path,
      fingerprint: fp,
    });
    // Arbitrary shell can mutate any file; no shell text is classified as read-only.
    if (["bash", "edit", "write"].includes(action.toolName)) {
      this.evidence = [];
      this.revision++;
    }
  }
  result(action: Action, content: unknown, isError: boolean, details: unknown) {
    const prior = this.pending.get(action.toolCallId);
    if (!prior) return; // Bloqueos no ejecutados no cambian el estado.
    this.pending.delete(action.toolCallId);
    this.revision++;
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
