import { randomUUID } from "node:crypto";
import { realpathSync } from "node:fs";
import {
  hash,
  type Action,
  type Config,
  type Decision,
  type Judgment,
  type Mode,
  type ReviewerClient,
  type Snapshot,
} from "./contracts.ts";
import { questionsHash, questionsFor } from "./questions.ts";
import {
  candidate,
  localJudgments,
  reason,
  localOnlyJudgments,
  validateResponse,
} from "./policy.ts";
import { buildContext } from "./context.ts";
import { assessSafety, safetyReason, type SafetyFinding } from "./safety.ts";
import { fingerprint, scopedPath, State } from "./state.ts";
import type { RecordWriter } from "./journal.ts";
const guardPatterns: Judgment["pattern"][] = ["unsafe_action", "test_tampering"];
export class Reviewer {
  readonly state: State;
  calls = 0;
  failures = 0;
  blocks = 0;
  // Jev safety/quality blocks have their own budget so efficiency blocks cannot exhaust it.
  guardBlocks = 0;
  safetyBlocks = 0;
  remoteTokens = 0;
  private controller = new AbortController();
  private blocked = new Map<string, string>();
  private bypass = new Set<string>();
  // Identical actions Jev already judged unsafe/tampering in this task stay blocked with no new
  // query or budget, like safety blocks: a stubborn model cannot outlast the budgets.
  private condemned = new Map<string, { pattern: Judgment["pattern"]; reference: string; reason: string; key: string }>();
  private condemnedBy = new Map<string, string>();
  // Safety blocks never auto-bypass on retry; only an explicit allow-once lifts them.
  private safetyBlocked = new Map<string, string>();
  private safetyBypass = new Set<string>();
  constructor(
    readonly config: Config,
    readonly client: ReviewerClient,
    readonly write: RecordWriter,
  ) {
    this.state = new State(config);
  }
  reset(clearObjective = false) {
    if (clearObjective) {
      this.condemned.clear();
      this.condemnedBy.clear();
    }
    this.controller.abort();
    this.controller = new AbortController();
    this.state.invalidate(clearObjective);
    this.blocked.clear();
    this.bypass.clear();
    this.safetyBlocked.clear();
    this.safetyBypass.clear();
  }
  setMode(mode: Mode) {
    this.reset();
    this.config.mode = mode;
    this.write({ kind: "mode", mode });
  }
  setSafety(mode: Mode) {
    this.reset();
    this.config.safety = mode;
    this.write({ kind: "safety_mode", mode });
  }
  allowOnce(reviewId: string): boolean {
    const condemnedKey = this.condemnedBy.get(reviewId);
    if (condemnedKey && this.condemned.has(condemnedKey)) {
      this.bypass.add(this.condemned.get(condemnedKey)!.key);
      this.condemned.delete(condemnedKey);
      this.write({ kind: "allow_once", reviewId });
      return true;
    }
    const safetyKey = this.safetyBlocked.get(reviewId);
    const key = safetyKey ?? this.blocked.get(reviewId);
    if (!key) return false;
    (safetyKey ? this.safetyBypass : this.bypass).add(key);
    this.write({ kind: "allow_once", reviewId });
    return true;
  }
  private key(s: Snapshot) {
    return hash({
      action: { toolName: s.action.toolName, input: s.action.input },
      session: s.sessionId,
      branch: s.branchId,
      task: s.taskVersion,
      revision: s.stateRevision,
      evidence: s.evidence.map((e) => [e.id, e.fingerprint]),
    });
  }
  private eligible(s: Snapshot): string | undefined {
    if (!this.config.scope) return "Sin alcance de datos autorizado.";
    try {
      if (realpathSync(s.cwd) !== realpathSync(this.config.scope.root))
        return "Directorio fuera del alcance.";
    } catch {
      return "Directorio no verificable.";
    }
    if (!["read", "bash", "edit", "write"].includes(s.action.toolName))
      return "Herramienta sin adaptador.";
    const fields: Record<string, string[]> = {
      read: ["path", "offset", "limit"],
      bash: ["command", "timeout"],
      edit: ["path", "edits", "oldText", "newText"],
      write: ["path", "content"],
    };
    if (
      Object.keys(s.action.input).some(
        (key) => !fields[s.action.toolName].includes(key),
      )
    )
      return "Campos sin autorización de envío.";
    if (
      s.action.toolName === "bash"
        ? !this.config.scope.allowBash
        : !scopedPath(this.config, s.cwd, s.action.input.path)
    )
      return "Acción fuera del alcance autorizado.";
    if (s.omissions.length || s.pending.length)
      return "Contexto incompleto o herramientas pendientes.";
    if (
      Buffer.byteLength(
        JSON.stringify(
          this.config.reviewer === "jev"
            ? {
                model: this.config.model,
                state: s,
                questions: questionsFor(s).questions,
              }
            : s,
        ),
      ) > this.config.maxInputBytes
    )
      return "Límite de contexto; abstención sin recortar.";
    return;
  }
  async review(
    action: Action,
    cwd: string,
    userSignal?: AbortSignal,
  ): Promise<Decision> {
    const start = performance.now();
    const snapshot = this.state.snapshot(action, cwd);
    if (
      this.config.reviewer === "jev" &&
      this.config.mode !== "off" &&
      this.config.scope &&
      ["bash", "edit", "write"].includes(action.toolName) &&
      !userSignal?.aborted
    ) {
      try {
        snapshot.context = buildContext(action, cwd, this.config, this.state.written, this.state.recent);
      } catch {
        // Without context Jev still answers on the action alone.
      }
    }
    const d: Decision = {
      schemaVersion: 1,
      kind: "decision",
      reviewId: randomUUID(),
      snapshot,
      mode: this.config.mode,
      reviewer: this.config.reviewer,
      action: "allow",
      wouldBlock: false,
      safetyMode: this.config.safety,
      reason: "Revisor apagado.",
      latencyMs: 0,
      requestedModel: this.config.model,
      policyHash: hash({
        calibration: this.config.calibration,
        maxBlocks: this.config.maxBlocksPerTask,
      }),
      questionsHash,
      extensionVersion: "0.1.0",
      provenance: "calculated",
      traceLink: "unlinked",
    };
    const invalid = this.eligible(snapshot);
    const active = this.config.mode !== "off" && this.config.reviewer !== "off";
    const key = this.key(snapshot);
    const actionKey = hash({
      action: { toolName: action.toolName, input: action.input },
      cwd,
      session: snapshot.sessionId,
      branch: snapshot.branchId,
      task: snapshot.taskVersion,
    });
    const prior = this.condemned.get(actionKey);
    let blockKey: string | undefined;
    let guardBlock = false;
    const max = this.config.maxBlocksPerTask;
    // Drop judgments whose block budget is spent; the other class can still block.
    const budgeted = (judgments: Judgment[]) =>
      judgments.filter((j) =>
        guardPatterns.includes(j.pattern) ? this.guardBlocks < max : this.blocks < max,
      );
    let safetyKey: string | undefined;
    const generation = this.controller.signal;
    const repeated = localOnlyJudgments(
      this.state.repeatedRun(action, cwd),
      this.state.blindOverwrite(action, cwd),
    );
    const apply = (problem: ReturnType<typeof candidate>) => {
      if (!problem) return;
      d.wouldBlock = true;
      d.pattern = problem.pattern;
      d.reference = problem.reference;
      d.reason = reason(problem, snapshot);
      if (this.config.mode === "enforce") {
        d.action = "block";
        blockKey = key;
        guardBlock = guardPatterns.includes(problem.pattern);
      }
    };
    // Safety is local and independent of the utility arm, data scope and budgets.
    let finding: SafetyFinding | undefined;
    if (this.config.safety !== "off" && !userSignal?.aborted) {
      try {
        finding = assessSafety(action, cwd, this.config.protectedPaths, this.state.written);
      } catch {
        // Fail closed for safety (unlike utility): an unanalyzable action needs the user.
        finding = { rule: "safety_error", verdict: "ask", detail: "No se pudo analizar la acción." };
      }
    }
    if (finding) {
      d.safety = finding;
      d.reason = safetyReason(finding);
      if (this.config.safety === "enforce" && !this.safetyBypass.delete(key)) {
        d.action = "block";
        d.wouldBlock = true;
        safetyKey = key;
      }
    }
    try {
      if (userSignal?.aborted) {
        d.action = "abstain";
        d.reason = "cancelled";
      } else if (safetyKey) {
        // Blocked for safety: no utility review or remote query is needed.
      } else if (active && this.config.mode === "enforce" && prior) {
        d.action = "block";
        d.wouldBlock = true;
        d.pattern = prior.pattern;
        d.reference = prior.reference;
        d.reason = `${prior.reason} Ya se bloqueó esta misma acción en esta tarea: no la repitas.`;
      } else if (
        active &&
        (this.bypass.delete(key) ||
          [...this.blocked.values()].includes(key) ||
          (this.blocks >= max &&
            (this.guardBlocks >= max ||
              !this.config.calibration.some(
                (c) => guardPatterns.includes(c.pattern) && c.tool === action.toolName,
              ))))
      ) {
        d.reason = "Bypass por autorización, reintento o límite de bloqueos.";
      } else if (active && invalid) {
        d.action = "abstain";
        d.reason = invalid;
        const problem = candidate(this.config, snapshot, budgeted(repeated));
        if (problem) {
          d.action = "allow";
          apply(problem);
        }
      } else if (active) {
        let judgments = [...localJudgments(snapshot), ...repeated];
        if (this.config.reviewer === "jev") {
          if (this.failures >= this.config.maxConsecutiveFailures)
            throw new Error("circuit_open");
          if (
            this.calls >= this.config.maxCallsPerTask ||
            this.remoteTokens >= this.config.maxRemoteTokens
          )
            throw new Error("budget_exhausted");
          this.calls++;
          const deadline = new AbortController();
          const timer = setTimeout(
            () => deadline.abort(),
            this.config.deadlineMs,
          );
          const signal = AbortSignal.any([
            generation,
            deadline.signal,
            ...(userSignal ? [userSignal] : []),
          ]);
          let onAbort: (() => void) | undefined;
          try {
            signal.throwIfAborted();
            d.response = await Promise.race([
              this.client(structuredClone(snapshot), signal),
              new Promise<never>((_, reject) => {
                onAbort = () => reject(new Error("aborted"));
                signal.addEventListener("abort", onAbort, { once: true });
              }),
            ]);
            validateResponse(d.response, snapshot);
            d.provenance = "reviewer_inferred";
            const usage = d.response.usage as
              | { input_tokens?: number; output_tokens?: number }
              | undefined;
            if (
              usage &&
              Number.isSafeInteger(usage.input_tokens) &&
              Number.isSafeInteger(usage.output_tokens) &&
              usage.input_tokens! >= 0 &&
              usage.output_tokens! >= 0
            ) {
              this.remoteTokens += usage.input_tokens! + usage.output_tokens!;
            } else {
              this.remoteTokens = this.config.maxRemoteTokens;
            }
            // Semantic verification can veto a local duplicate candidate.
            judgments = [...d.response.judgments, ...repeated];
            this.failures = 0;
          } finally {
            clearTimeout(timer);
            if (onAbort) signal.removeEventListener("abort", onAbort);
          }
        }
        if (
          generation.aborted ||
          userSignal?.aborted ||
          this.state.revision !== snapshot.stateRevision ||
          snapshot.evidence.some(
            (e) =>
              fingerprint(e.path, this.config.maxInputBytes) !== e.fingerprint,
          )
        ) {
          d.action = "abstain";
          d.reason = userSignal?.aborted
            ? "cancelled"
            : "Estado obsoleto; respuesta descartada.";
        } else {
          const problem = candidate(this.config, snapshot, budgeted(judgments));
          if (!finding) d.reason = "Sin patrón calibrado aplicable.";
          apply(problem);
        }
      }
    } catch (error) {
      const code = error instanceof Error ? error.message : "";
      const budget = ["circuit_open", "budget_exhausted"].includes(code);
      if (!generation.aborted && !userSignal?.aborted && !budget)
        this.failures++;
      const status = (error as { status?: number } | null)?.status;
      d.action = "abstain";
      d.reason = userSignal?.aborted
        ? "cancelled"
        : generation.aborted
          ? "state_invalidated"
          : budget
            ? code
            : status === 429
              ? "rate_limited"
              : code === "aborted"
                ? "deadline_exceeded"
                : "reviewer_error";
    }
    d.latencyMs = performance.now() - start;
    // Unauthorized payloads are not persisted, even when off.
    if (invalid)
      d.snapshot = {
        ...snapshot,
        objective: [],
        requirements: [],
        evidence: [],
        action: { ...action, input: {} },
        context: undefined,
      };
    try {
      this.write(d as unknown as Record<string, unknown>);
    } catch {
      d.action = "abstain";
      d.reason = "Journal no disponible; no se aplica el bloqueo.";
      blockKey = undefined;
      // A safety block does not depend on the journal: it stays blocked.
      if (safetyKey) {
        d.action = "block";
        d.reason = safetyReason(d.safety!);
      }
    }
    if (safetyKey) {
      this.safetyBlocked.set(d.reviewId, safetyKey);
      this.safetyBlocks++;
    }
    if (d.action === "block" && prior && !safetyKey) this.condemnedBy.set(d.reviewId, actionKey);
    if (blockKey && guardBlock) {
      this.condemned.set(actionKey, { pattern: d.pattern!, reference: d.reference!, reason: d.reason, key: blockKey });
      this.condemnedBy.set(d.reviewId, actionKey);
    }
    if (blockKey) {
      this.blocked.set(d.reviewId, blockKey);
      if (guardBlock) this.guardBlocks++;
      else this.blocks++;
    }
    return d;
  }
}
