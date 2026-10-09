import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
  readdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { readRecords } from "../src/report.ts";

for (const mode of ["off", "enforce"])
  test(
    `Pi 0.85.1 real: ${mode}, IDs y recuperación con modelo HTTP simulado`,
    { timeout: 30000 },
    async (t) => {
      const root = mkdtempSync(join(tmpdir(), "jev-pi-"));
      t.after(() => rmSync(root, { recursive: true, force: true }));
      const cwd = join(root, "work");
      const agent = join(root, "agent");
      mkdirSync(cwd);
      mkdirSync(agent);
      writeFileSync(join(cwd, "a.txt"), "Evidencia sintética\n");
      let requests = 0;
      const bodies: string[] = [];
      const server = createServer(async (req, res) => {
        let body = "";
        for await (const chunk of req) body += chunk;
        bodies.push(body);
        requests++;
        res.writeHead(200, { "content-type": "text/event-stream" });
        const call =
          requests <= 2
            ? {
                index: 0,
                id: `call_${requests}`,
                type: "function",
                function: {
                  name: "read",
                  arguments: JSON.stringify({ path: "a.txt" }),
                },
              }
            : requests === 3
              ? {
                  index: 0,
                  id: "call_3",
                  type: "function",
                  function: {
                    name: "write",
                    arguments: JSON.stringify({
                      path: "done.txt",
                      content: "Hecho",
                    }),
                  },
                }
              : undefined;
        const chunk = (delta: unknown, finish_reason: string | null) =>
          `data: ${JSON.stringify({ id: `chat_${requests}`, object: "chat.completion.chunk", created: 1, model: "fixture", choices: [{ index: 0, delta, finish_reason }] })}\n\n`;
        res.write(
          chunk(
            call
              ? { role: "assistant", tool_calls: [call] }
              : { role: "assistant", content: "Hecho." },
            null,
          ),
        );
        res.write(chunk({}, call ? "tool_calls" : "stop"));
        res.end("data: [DONE]\n\n");
      });
      await new Promise<void>((resolve) =>
        server.listen(0, "127.0.0.1", resolve),
      );
      t.after(() => {
        server.closeAllConnections();
        server.close();
      });
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      writeFileSync(
        join(agent, "models.json"),
        JSON.stringify({
          providers: {
            fixture: {
              baseUrl: `http://127.0.0.1:${address.port}/v1`,
              api: "openai-completions",
              apiKey: "synthetic",
              models: [
                {
                  id: "fixture",
                  name: "Fixture",
                  reasoning: false,
                  input: ["text"],
                  contextWindow: 32000,
                  maxTokens: 1024,
                  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
                },
              ],
            },
          },
        }),
      );
      const config = join(root, "config.json");
      writeFileSync(
        config,
        JSON.stringify({
          mode,
          reviewer: "local",
          storageRoot: join(root, "reviews"),
          scope: {
            root: cwd,
            paths: ["a.txt", "done.txt"],
            allowBash: false,
            authorization: "Sintético",
          },
          calibration: [
            {
              pattern: "redundant_read",
              tool: "read",
              threshold: 1,
              reference: "integration-test-only",
            },
          ],
        }),
      );
      const cli = fileURLToPath(
        new URL(
          "../node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
          import.meta.url,
        ),
      );
      const extension = fileURLToPath(
        new URL("../src/index.ts", import.meta.url),
      );
      const session = join(root, "session.jsonl");
      const child = spawn(
        process.execPath,
        [
          cli,
          "--no-extensions",
          "--no-skills",
          "--no-prompt-templates",
          "-e",
          extension,
          "--jev-config",
          config,
          "--provider",
          "fixture",
          "--model",
          "fixture",
          "--thinking",
          "off",
          "--mode",
          "json",
          "--session",
          session,
          "-p",
          "Lee a.txt y escribe done.txt.",
        ],
        {
          cwd,
          env: {
            ...process.env,
            PI_CODING_AGENT_DIR: agent,
            JEV_MODE: "",
            JEV_REVIEWER: "",
            TYPESAFE_API_KEY: "",
          },
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
      let stdout = "",
        stderr = "";
      child.stdout.on("data", (c) => {
        stdout += c;
      });
      child.stderr.on("data", (c) => {
        stderr += c;
      });
      t.after(() => child.kill());
      const code = await new Promise<number | null>((resolve) =>
        child.on("close", resolve),
      );
      assert.equal(code, 0, stderr + stdout);
      assert.equal(requests, 4, stderr + stdout);
      assert.equal(readFileSync(join(cwd, "done.txt"), "utf8"), "Hecho");
      const sessionDir = join(
        root,
        "reviews",
        readdirSync(join(root, "reviews"))[0],
      );
      const branchDir = join(sessionDir, readdirSync(sessionDir)[0]);
      const records = readRecords(join(branchDir, "events.jsonl"));
      const decisions = records.filter((r) => r.kind === "decision");
      assert.equal(decisions.length, 3);
      assert.equal(
        decisions[1].action,
        mode === "enforce" ? "block" : "allow",
        JSON.stringify(decisions),
      );
      assert.equal(
        bodies[2].includes("La lectura repite información vigente"),
        mode === "enforce",
      );
      const raw = readFileSync(session, "utf8");
      for (const d of decisions) {
        const s = d.snapshot as {
          sessionId: string;
          action: { toolCallId: string };
        };
        assert.ok(raw.includes(s.sessionId));
        assert.ok(raw.includes(s.action.toolCallId));
      }
    },
  );
