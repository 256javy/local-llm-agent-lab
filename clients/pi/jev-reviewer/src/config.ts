import { readFileSync } from "node:fs";
import { isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { patterns, type Config } from "./contracts.ts";
import { defaultProtectedPaths } from "./safety.ts";
export const defaults: Config = {
  mode: "off",
  reviewer: "jev",
  model: "jev-latest",
  deadlineMs: 1500,
  maxCallsPerTask: 100,
  maxRemoteTokens: 50000,
  maxInputBytes: 16384,
  maxBlocksPerTask: 5,
  maxConsecutiveFailures: 3,
  maxIdenticalFailures: 6,
  storageRoot: fileURLToPath(
    new URL("../../../../.local/jev-reviews/", import.meta.url),
  ),
  safety: "enforce",
  protectedPaths: defaultProtectedPaths,
  requirements: [],
  calibration: [],
};
export function validateConfig(value: unknown): Config {
  const c = { ...defaults, ...(value as object) };
  if (
    !["off", "observe", "enforce"].includes(c.mode) ||
    !["off", "local", "jev"].includes(c.reviewer) ||
    !["off", "observe", "enforce"].includes(c.safety)
  )
    throw new Error("Modo o revisor inválido.");
  for (const key of [
    "deadlineMs",
    "maxCallsPerTask",
    "maxInputBytes",
    "maxRemoteTokens",
    "maxBlocksPerTask",
    "maxConsecutiveFailures",
    "maxIdenticalFailures",
  ] as const) {
    if (!Number.isSafeInteger(c[key]) || c[key] <= 0)
      throw new Error(`Límite inválido: ${key}`);
  }
  if (
    !Array.isArray(c.protectedPaths) ||
    c.protectedPaths.some((p) => typeof p !== "string" || !p || p.includes("/"))
  )
    throw new Error("protectedPaths inválido: patrones de segmento sin '/'.");
  if (!isAbsolute(c.storageRoot) || typeof c.model !== "string" || !c.model)
    throw new Error("Se requiere storageRoot absoluto y modelo.");
  if (
    !Array.isArray(c.requirements) ||
    c.requirements.some((r) => !r.id || typeof r.text !== "string") ||
    new Set(c.requirements.map((r) => r.id)).size !== c.requirements.length
  )
    throw new Error("Requisitos inválidos.");
  if (
    !Array.isArray(c.calibration) ||
    c.calibration.some(
      (p) =>
        !patterns.includes(p.pattern) ||
        !["read", "bash", "edit", "write"].includes(p.tool) ||
        !Number.isFinite(p.threshold) ||
        p.threshold < 0 ||
        p.threshold > 1 ||
        !p.reference,
    )
  )
    throw new Error("Calibración inválida.");
  if (
    c.scope &&
    (!isAbsolute(c.scope.root) ||
      !Array.isArray(c.scope.paths) ||
      c.scope.paths.some(
        (p) =>
          typeof p !== "string" || isAbsolute(p) || p.split("/").includes(".."),
      ) ||
      typeof c.scope.allowBash !== "boolean" ||
      !c.scope.authorization)
  )
    throw new Error("Alcance autorizado inválido.");
  return c;
}
export function loadConfig(path?: string): Config {
  return validateConfig(path ? JSON.parse(readFileSync(path, "utf8")) : {});
}
