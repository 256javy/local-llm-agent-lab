import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import type { Decision } from "./contracts.ts";
export function report(records: Record<string, unknown>[]) {
  const decisions = records.filter(
    (r) => r.kind === "decision",
  ) as unknown as Decision[];
  const results = records.filter((r) => r.kind === "tool_result");
  const rows = decisions.map((d) => ({
    reviewId: d.reviewId,
    toolCallId: d.snapshot.action.toolCallId,
    tool: d.snapshot.action.toolName,
    action: d.action,
    wouldBlock: d.wouldBlock,
    pattern: d.pattern ?? "none",
    reason: d.reason,
  }));
  return {
    schemaVersion: 1,
    provenance: "calculated",
    proposed: decisions.length,
    executedResults: results.length,
    blocked: decisions.filter((d) => d.action === "block").length,
    wouldBlock: decisions.filter((d) => d.wouldBlock).length,
    abstained: decisions.filter((d) => d.action === "abstain").length,
    reviewerMs: decisions.reduce((sum, d) => sum + d.latencyMs, 0),
    remoteResponses: decisions.filter((d) => d.response).length,
    remoteUsage: decisions.flatMap((d) =>
      d.response ? [d.response.usage] : [],
    ),
    cost: "unknown",
    outcome: "unknown",
    traceLink: "unlinked",
    rows,
  };
}
export function readRecords(path: string) {
  return readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const path = process.argv[2];
  if (!path)
    throw new Error("Uso: npm run report -- /ruta/events.jsonl [--markdown]");
  const result = report(readRecords(path));
  if (process.argv.includes("--markdown")) {
    console.log(
      `# Revisión Jev\n\nPropuestas: ${result.proposed}. Bloqueadas: ${result.blocked}. Abstenciones: ${result.abstained}.\n\nResultado de tarea y coste: unknown.\n`,
    );
    for (const row of result.rows)
      console.log(
        `- ${row.reviewId}: ${row.tool}, ${row.action}. ${row.reason}`,
      );
  } else console.log(JSON.stringify(result, null, 2));
}
