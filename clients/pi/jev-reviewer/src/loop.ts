import { hash } from "./contracts.ts";

// Detects the same failing tool call repeated back to back. It works on finalized
// messages because calls rejected by argument validation never reach tool_call/tool_result.
export interface LoopVerdict {
  streak: number;
  toolName: string;
  action: "hint" | "abort";
}
interface Message {
  role?: string;
  content?: unknown;
  toolCallId?: string;
  toolName?: string;
  isError?: boolean;
}
export class LoopGuard {
  private calls = new Map<string, string>();
  private last?: string;
  streak = 0;
  constructor(readonly maxIdenticalFailures: number) {}
  assistant(message: Message) {
    if (!Array.isArray(message.content)) return;
    for (const c of message.content as { type?: string; id?: string; name?: string; arguments?: unknown }[])
      if (c?.type === "toolCall" && c.id)
        this.calls.set(c.id, hash({ name: c.name, arguments: c.arguments }));
  }
  result(message: Message): LoopVerdict | undefined {
    const signature = message.toolCallId ? this.calls.get(message.toolCallId) : undefined;
    if (message.toolCallId) this.calls.delete(message.toolCallId);
    if (!signature || !message.isError) {
      this.last = undefined;
      this.streak = 0;
      return;
    }
    this.streak = signature === this.last ? this.streak + 1 : 1;
    this.last = signature;
    if (this.streak < 2) return;
    return {
      streak: this.streak,
      toolName: message.toolName ?? "unknown",
      action: this.streak >= this.maxIdenticalFailures ? "abort" : "hint",
    };
  }
  reset() {
    this.calls.clear();
    this.last = undefined;
    this.streak = 0;
  }
}
export function loopHint(v: LoopVerdict): string {
  return `\n\n[Jev] Es el intento idéntico número ${v.streak} de ${v.toolName} y falla igual. No repitas la misma llamada: lee el error, corrige los argumentos (revisa los campos obligatorios) o cambia de enfoque, por ejemplo con otra herramienta.`;
}
