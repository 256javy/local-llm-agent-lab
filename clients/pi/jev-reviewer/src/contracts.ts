import { createHash } from "node:crypto";

export const patterns = [
  "redundant_read",
  "task_conflict",
  "refuted_precondition",
  "off_task_action",
] as const;
export type Pattern = (typeof patterns)[number];
export type Mode = "off" | "observe" | "enforce";
export type Arm = "off" | "local" | "jev";
export type Tool = "read" | "bash" | "edit" | "write";
export interface Action {
  toolCallId: string;
  toolName: string;
  input: Record<string, unknown>;
}
export interface Requirement {
  id: string;
  text: string;
}
export interface Evidence {
  id: string;
  path: string;
  fingerprint: string;
  input: Record<string, unknown>;
  text: string;
  available: boolean;
}
export interface Snapshot {
  schemaVersion: 1;
  sessionId: string;
  branchId: string;
  taskVersion: number;
  stateRevision: number;
  cwd: string;
  objective: string[];
  requirements: Requirement[];
  action: Action;
  evidence: Evidence[];
  pending: string[];
  omissions: string[];
}
export interface Judgment {
  pattern: Pattern;
  reference: string;
  choice: "problem" | "useful" | "uncertain";
  confidence: number;
  probabilities: Record<string, number>;
}
export interface ReviewResponse {
  model: string;
  judgments: Judgment[];
  usage: unknown;
}
export interface Calibration {
  pattern: Pattern;
  tool: Tool;
  threshold: number;
  reference: string;
}
export interface Config {
  mode: Mode;
  reviewer: Arm;
  model: string;
  deadlineMs: number;
  maxCallsPerTask: number;
  maxInputBytes: number;
  maxRemoteTokens: number;
  maxBlocksPerTask: number;
  maxConsecutiveFailures: number;
  storageRoot: string;
  scope?: {
    root: string;
    paths: string[];
    allowBash: boolean;
    authorization: string;
  };
  requirements: Requirement[];
  calibration: Calibration[];
}
export interface Decision {
  schemaVersion: 1;
  kind: "decision";
  reviewId: string;
  snapshot: Snapshot;
  mode: Mode;
  reviewer: Arm;
  action: "allow" | "block" | "abstain";
  wouldBlock: boolean;
  pattern?: Pattern;
  reference?: string;
  reason: string;
  latencyMs: number;
  requestedModel: string;
  response?: ReviewResponse;
  policyHash: string;
  questionsHash: string;
  extensionVersion: "0.1.0";
  provenance: "reviewer_inferred" | "calculated";
  traceLink: "unlinked";
}
export const hash = (value: unknown): string =>
  createHash("sha256").update(JSON.stringify(value)).digest("hex");
export type ReviewerClient = (
  snapshot: Snapshot,
  signal: AbortSignal,
) => Promise<ReviewResponse>;
