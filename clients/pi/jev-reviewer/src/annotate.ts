import { appendFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { readRecords } from "./report.ts";
const [path, reviewId, label, ...notes] = process.argv.slice(2);
if (
  !path ||
  !["justified", "false_positive", "uncertain"].includes(label) ||
  !notes.length
)
  throw new Error(
    "Uso: npm run annotate -- /ruta/events.jsonl review-id justified|false_positive|uncertain nota",
  );
if (
  !readRecords(path).some(
    (r) => r.kind === "decision" && r.reviewId === reviewId,
  )
)
  throw new Error("Review inexistente.");
appendFileSync(
  join(dirname(path), "annotations.jsonl"),
  JSON.stringify({
    schemaVersion: 1,
    at: new Date().toISOString(),
    reviewId,
    label,
    note: notes.join(" "),
    provenance: "human_annotated",
  }) + "\n",
  { mode: 0o600 },
);
