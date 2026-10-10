import { appendFileSync, chmodSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { hash } from "./contracts.ts";
export type RecordWriter = (record: Record<string, unknown>) => void;
export class Journal {
  readonly directory: string;
  constructor(root: string, sessionId: string, branchId: string) {
    this.directory = join(
      root,
      hash(sessionId).slice(0, 24),
      hash(branchId).slice(0, 24),
    );
    for (const directory of [
      root,
      join(root, hash(sessionId).slice(0, 24)),
      this.directory,
    ]) {
      mkdirSync(directory, { recursive: true, mode: 0o700 });
      chmodSync(directory, 0o700);
    }
  }
  write: RecordWriter = (record) => {
    const path = join(this.directory, "events.jsonl");
    appendFileSync(
      path,
      JSON.stringify({
        schemaVersion: 1,
        at: new Date().toISOString(),
        ...record,
      }) + "\n",
      { mode: 0o600 },
    );
    chmodSync(path, 0o600);
  };
}
