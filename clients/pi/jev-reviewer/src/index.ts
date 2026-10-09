import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { loadConfig, validateConfig } from "./config.ts";
import { createJevClient } from "./jev-client.ts";
import { Journal } from "./journal.ts";
import { Reviewer } from "./reviewer.ts";
import { hash, type Action, type Mode } from "./contracts.ts";

export default function extension(pi: ExtensionAPI) {
  pi.registerFlag("jev-mode", {
    description: "Revisor: off, observe o enforce.",
    type: "string",
  });
  pi.registerFlag("jev-reviewer", {
    description: "Brazo: off, local o jev.",
    type: "string",
  });
  pi.registerFlag("jev-safety", {
    description: "Guardia de seguridad local: off, observe o enforce (predeterminado).",
    type: "string",
  });
  pi.registerFlag("jev-config", {
    description: "Configuración y alcance de datos autorizado (JSON).",
    type: "string",
  });
  let reviewer: Reviewer | undefined;
  let journal: Journal | undefined;
  function notice(ctx: ExtensionContext, text: string) {
    if (ctx.hasUI) ctx.ui.notify(text, "info");
    else process.stderr.write(text + "\n");
  }
  pi.on("session_start", (_event, ctx) => {
    try {
      const path = pi.getFlag("jev-config") ?? process.env.JEV_CONFIG;
      const config = loadConfig(typeof path === "string" ? path : undefined);
      const mode = pi.getFlag("jev-mode") ?? process.env.JEV_MODE;
      const arm = pi.getFlag("jev-reviewer") ?? process.env.JEV_REVIEWER;
      const safety = pi.getFlag("jev-safety") ?? process.env.JEV_SAFETY;
      Object.assign(
        config,
        validateConfig({
          ...config,
          ...(mode ? { mode } : {}),
          ...(arm ? { reviewer: arm } : {}),
          ...(safety ? { safety } : {}),
        }),
      );
      const sessionId = ctx.sessionManager.getSessionId();
      const branchId = ctx.sessionManager.getLeafId() ?? "root";
      journal = new Journal(config.storageRoot, sessionId, branchId);
      reviewer = new Reviewer(config, createJevClient(config), journal.write);
      if (
        ctx.sessionManager
          .getBranch()
          .some(
            (entry) => entry.type === "message" || entry.type === "compaction",
          )
      )
        reviewer.reset(true);
      reviewer.state.sessionId = sessionId;
      reviewer.state.branchId = branchId;
      journal.write({
        kind: "start",
        sessionId,
        branchId,
        mode: config.mode,
        reviewer: config.reviewer,
        safety: config.safety,
        model: config.model,
        localModel: ctx.model?.id ?? "unknown",
        configHash: hash(config),
        piVersion: "0.85.1",
        traceLink: "unlinked",
      });
      notice(
        ctx,
        `Jev: ${config.mode}, brazo ${config.reviewer}; seguridad ${config.safety}.`,
      );
    } catch {
      reviewer = undefined;
      notice(ctx, "Jev desactivado: configuración o journal inválidos.");
    }
  });
  pi.on("before_agent_start", (event, ctx) => {
    if (reviewer) {
      reviewer.reset();
      reviewer.state.input(event.prompt);
      try {
        journal?.write({
          kind: "context",
          taskVersion: reviewer.state.taskVersion,
          sourceEntryId: ctx.sessionManager.getLeafId(),
          systemPromptHash: hash(event.systemPrompt),
          provenance: "observed",
        });
      } catch {
        reviewer.reset(true);
      }
    }
  });
  pi.on("session_compact", () => reviewer?.reset(true));
  pi.on("session_tree", (_event, ctx) => {
    if (!reviewer) return;
    reviewer.reset(true);
    reviewer.state.branchId = ctx.sessionManager.getLeafId() ?? "root";
    try {
      journal = new Journal(
        reviewer.config.storageRoot,
        reviewer.state.sessionId,
        reviewer.state.branchId,
      );
    } catch {
      reviewer = undefined;
    }
    if (reviewer && journal) {
      const prior = reviewer;
      reviewer = new Reviewer(
        prior.config,
        createJevClient(prior.config),
        journal.write,
      );
      reviewer.state.sessionId = prior.state.sessionId;
      reviewer.state.branchId = prior.state.branchId;
      reviewer.state.incompleteHistory = true;
    }
  });
  pi.on("session_shutdown", () => {
    reviewer?.reset(true);
    reviewer = undefined;
  });
  pi.on("tool_call", async (event, ctx) => {
    if (!reviewer) return;
    const current = reviewer;
    try {
      const action: Action = {
        toolCallId: event.toolCallId,
        toolName: event.toolName,
        input: structuredClone(event.input),
      };
      const result = await current.review(action, ctx.cwd, ctx.signal);
      if (ctx.signal?.aborted)
        return { block: true, reason: "Tarea cancelada por el usuario." };
      if (
        result.action === "block" &&
        result.safety?.verdict === "ask" &&
        ctx.hasUI
      ) {
        // Like a permission prompt: the user decides, the model never does.
        const ok = await ctx.ui.confirm(
          "Jev: confirmar acción",
          `${result.safety.detail}\n\n${String(action.input.command ?? action.input.path ?? "")}`,
        );
        try {
          current.write({ kind: "safety_confirm", reviewId: result.reviewId, allowed: ok });
        } catch {
          // The user's decision stands even if it cannot be journaled.
        }
        if (!ok)
          return { block: true, reason: `${result.reason} El usuario la rechazó. [${result.reviewId}]` };
      } else if (result.action === "block")
        return { block: true, reason: `${result.reason} [${result.reviewId}]` };
      current.state.before(action, ctx.cwd);
    } catch {
      current.reset();
      notice(ctx, "Fallo del revisor; la herramienta continúa.");
    }
  });
  pi.on("tool_result", (event) => {
    if (!reviewer) return;
    try {
      const executed = reviewer.state.pending.has(event.toolCallId);
      reviewer.state.result(event, event.content, event.isError, event.details);
      journal?.write({
        kind: executed ? "tool_result" : "unobserved_result",
        toolCallId: event.toolCallId,
        toolName: event.toolName,
        isError: event.isError,
        provenance: "observed",
      });
    } catch {
      reviewer.reset();
    }
  });
  pi.registerCommand("jev", {
    description:
      "status | mode off/observe/enforce | safety off/observe/enforce | allow-once <review-id> | task <objetivo completo>",
    handler: async (args, ctx) => {
      if (!reviewer) {
        notice(
          ctx,
          "Revisor no disponible. Revisa la configuración y recarga.",
        );
        return;
      }
      const [command, value] = args.trim().split(/\s+/);
      try {
        if (command === "task" && args.trim().slice(5).trim()) {
          reviewer.reset(true);
          reviewer.state.startTask(args.trim().slice(5).trim());
          journal?.write({
            kind: "task_reset",
            taskVersion: reviewer.state.taskVersion,
          });
        } else if (
          command === "mode" &&
          ["off", "observe", "enforce"].includes(value)
        )
          reviewer.setMode(value as Mode);
        else if (
          command === "safety" &&
          ["off", "observe", "enforce"].includes(value)
        )
          reviewer.setSafety(value as Mode);
        else if (command === "allow-once") {
          notice(
            ctx,
            reviewer.allowOnce(value)
              ? "Reintento autorizado para el mismo estado."
              : "Review desconocido o invalidado.",
          );
          return;
        } else if (command && command !== "status") {
          notice(
            ctx,
            "Uso: /jev status | mode off/observe/enforce | safety off/observe/enforce | allow-once <review-id>",
          );
          return;
        }
        notice(
          ctx,
          `Jev: ${reviewer.config.mode}; brazo ${reviewer.config.reviewer}; seguridad ${reviewer.config.safety}; consultas ${reviewer.calls}; bloqueos ${reviewer.blocks}; bloqueos de seguridad ${reviewer.safetyBlocks}; fallos consecutivos ${reviewer.failures}.`,
        );
      } catch {
        notice(ctx, "No se pudo registrar el cambio del revisor.");
      }
    },
  });
}
