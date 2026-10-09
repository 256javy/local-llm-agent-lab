import { resolve } from "node:path";
import {
  hash,
  patterns,
  type Config,
  type Judgment,
  type Snapshot,
  type ReviewResponse,
} from "./contracts.ts";
export function localJudgments(s: Snapshot): Judgment[] {
  if (s.action.toolName !== "read" || s.pending.length || s.omissions.length)
    return [];
  return s.evidence
    .filter(
      (e) =>
        e.path === resolve(s.cwd, String(s.action.input.path)) &&
        hash({ ...e.input, path: e.path }) ===
          hash({ ...s.action.input, path: e.path }),
    )
    .map((e) => ({
      pattern: "redundant_read",
      reference: e.id,
      choice: "problem",
      confidence: 1,
      probabilities: { problem: 1, useful: 0, uncertain: 0 },
    }));
}
export function validateResponse(response: ReviewResponse, s: Snapshot): void {
  if (
    !response ||
    typeof response.model !== "string" ||
    !Array.isArray(response.judgments)
  )
    throw new Error("Respuesta inválida.");
  for (const j of response.judgments) {
    const refs =
      j.pattern === "task_conflict"
        ? s.requirements.map((r) => r.id)
        : j.pattern === "off_task_action"
          ? ["objective"]
          : s.evidence.map((e) => e.id);
    if (
      !patterns.includes(j.pattern) ||
      !refs.includes(j.reference) ||
      !["problem", "useful", "uncertain"].includes(j.choice) ||
      !Number.isFinite(j.confidence) ||
      j.confidence < 0 ||
      j.confidence > 1 ||
      !j.probabilities ||
      ["problem", "useful", "uncertain"].some(
        (k) =>
          !Number.isFinite(j.probabilities[k]) ||
          j.probabilities[k] < 0 ||
          j.probabilities[k] > 1,
      ) ||
      Math.abs(Object.values(j.probabilities).reduce((a, b) => a + b, 0) - 1) >
        0.001
    )
      throw new Error("Respuesta inválida.");
  }
}
export function candidate(config: Config, s: Snapshot, judgments: Judgment[]) {
  if (s.pending.length || s.omissions.length) return;
  return judgments.find(
    (j) =>
      j.choice === "problem" &&
      (j.pattern !== "redundant_read" ||
        localJudgments(s).some((local) => local.reference === j.reference)) &&
      config.calibration.some(
        (c) =>
          c.pattern === j.pattern &&
          c.tool === s.action.toolName &&
          j.confidence >= c.threshold,
      ),
  );
}
export function reason(j: Judgment, snapshot: Snapshot): string {
  const labels = {
    redundant_read: "La lectura repite información vigente",
    task_conflict: "La acción contradice un requisito explícito",
    refuted_precondition: "La evidencia refuta una premisa de la acción",
    off_task_action: "La acción se desvía del objetivo",
  };
  const requirement = snapshot.requirements.find((r) => r.id === j.reference);
  const detail =
    j.pattern === "task_conflict" && requirement
      ? ` Requisito: ${requirement.text}.`
      : "";
  return `${labels[j.pattern]} (referencia ${j.reference}).${detail} Replantea el paso usando esa referencia.`;
}
