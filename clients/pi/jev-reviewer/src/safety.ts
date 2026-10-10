import { spawnSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import type { Action } from "./contracts.ts";

// Deterministic, local-only guard: nothing here is sent to a remote service.
// It is a conservative net for small models, not a sandbox: obfuscated shell
// (variables, eval of generated text, scripts written then executed) can evade it.
export type SafetyVerdict = "block" | "ask";
export interface SafetyFinding {
  rule: string;
  verdict: SafetyVerdict;
  detail: string;
}
export const defaultProtectedPaths = [".env", ".env.*", ".git"];

interface Command {
  words: string[];
  redirects: string[];
  nested: string[];
  pipedFrom?: Command;
}

const shells = ["sh", "bash", "zsh", "dash", "fish", "ksh"];
const interpreters = [...shells, "python", "python3", "node", "perl", "ruby"];
const wrappers = ["env", "nohup", "time", "nice", "ionice", "command", "exec", "builtin", "stdbuf"];

/** Splits shell text into simple commands; quotes, escapes and substitutions are tracked roughly. */
export function parseShell(text: string): Command[] {
  const commands: Command[] = [];
  let current: Command = { words: [], redirects: [], nested: [] };
  let word = "";
  let started = false;
  let quote: "'" | '"' | undefined;
  let redirect = false;
  const pushWord = () => {
    if (!started) return;
    if (redirect) {
      if (!word.startsWith("&")) current.redirects.push(word);
      redirect = false;
    } else current.words.push(word);
    word = "";
    started = false;
  };
  const end = (piped = false) => {
    pushWord();
    const done = current;
    if (done.words.length || done.redirects.length || done.nested.length)
      commands.push(done);
    current = { words: [], redirects: [], nested: [], ...(piped ? { pipedFrom: done } : {}) };
  };
  const capture = (start: number, open: string, close: string): number => {
    let depth = 1;
    let i = start;
    for (; i < text.length && depth; i++) {
      if (text[i] === open) depth++;
      else if (text[i] === close) depth--;
    }
    current.nested.push(text.slice(start, i - 1));
    return i - 1;
  };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const next = text[i + 1];
    if (quote === "'") {
      if (c === "'") quote = undefined;
      else word += c;
      continue;
    }
    if (c === "\\" && next !== undefined) {
      word += next;
      started = true;
      i++;
      continue;
    }
    if ((c === "$" || c === "<" || c === ">") && next === "(") {
      i = capture(i + 2, "(", ")");
      word += "$SUBST";
      started = true;
      continue;
    }
    if (c === "`") {
      const close = text.indexOf("`", i + 1);
      const stop = close < 0 ? text.length : close;
      current.nested.push(text.slice(i + 1, stop));
      word += "$SUBST";
      started = true;
      i = stop;
      continue;
    }
    if (quote === '"') {
      if (c === '"') quote = undefined;
      else word += c;
      continue;
    }
    if (c === "'" || c === '"') {
      quote = c;
      started = true;
      continue;
    }
    if (c === "#" && !started) {
      while (i < text.length && text[i] !== "\n") i++;
      end();
      continue;
    }
    if (c === " " || c === "\t") {
      pushWord();
      continue;
    }
    if (c === "\n" || c === ";") {
      end();
      continue;
    }
    if (c === "&" && next === "&") {
      end();
      i++;
      continue;
    }
    if (c === "|" && next === "|") {
      end();
      i++;
      continue;
    }
    if (c === "|") {
      end(true);
      if (next === "&") i++;
      continue;
    }
    if (c === "&" && next === ">") {
      pushWord();
      redirect = true;
      i += text[i + 2] === ">" ? 2 : 1;
      continue;
    }
    if (c === "&") {
      end();
      continue;
    }
    if (c === ">" || c === "<") {
      if (/^\d+$/.test(word)) {
        word = "";
        started = false;
      }
      pushWord();
      if (next === ">" || next === "|") i++;
      if (c === "<") {
        // Input redirection: the following word is a source, not a write target.
        if (text[i + 1] === "<") i++;
        continue;
      }
      redirect = true;
      continue;
    }
    word += c;
    started = true;
  }
  end();
  return commands;
}

function strip(words: string[]): { words: string[]; sudo: boolean } {
  let sudo = false;
  let rest = words;
  for (;;) {
    while (rest.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(rest[0]))
      rest = rest.slice(1);
    const name = rest.length ? basename(rest[0]) : "";
    if (["sudo", "doas", "su", "pkexec", "run0"].includes(name)) {
      sudo = true;
      rest = rest.slice(1);
      while (rest.length && rest[0].startsWith("-")) rest = rest.slice(1);
    } else if (wrappers.includes(name)) {
      rest = rest.slice(1);
      while (rest.length && rest[0].startsWith("-")) rest = rest.slice(1);
    } else if (name === "timeout") {
      rest = rest.slice(1);
      while (rest.length && rest[0].startsWith("-")) rest = rest.slice(1);
      rest = rest.slice(1);
    } else return { words: rest, sudo };
  }
}

export class SafetyGuard {
  private readonly home = homedir();
  private readonly tmp = resolve(tmpdir());
  // Directory the next shell command runs in; follows `cd` within one command line.
  private dir: string;
  // Literal shell variables assigned earlier in the analyzed text (e.g. inside a script).
  private vars = new Map<string, string>();
  private gitRoot: string | null | undefined;
  constructor(
    readonly cwd: string,
    readonly protectedPaths: string[] = defaultProtectedPaths,
    // Files the agent itself created in this session: deleting them is not irreversible loss.
    readonly agentFiles: ReadonlySet<string> = new Set(),
  ) {
    this.dir = cwd;
  }
  /** Untracked, non-ignored files under `p`: git cannot bring them back once deleted. */
  private untracked(p: string): string[] {
    if (this.gitRoot === undefined) {
      const r = spawnSync("git", ["rev-parse", "--show-toplevel"], { cwd: this.cwd, encoding: "utf8", timeout: 2000 });
      this.gitRoot = r.status === 0 ? r.stdout.trim() : null;
    }
    if (!this.gitRoot) return [];
    const r = spawnSync("git", ["ls-files", "--others", "--exclude-standard", "-z", "--", p], {
      cwd: this.cwd,
      encoding: "utf8",
      timeout: 2000,
    });
    if (r.status !== 0) return [];
    return r.stdout
      .split("\0")
      .filter(Boolean)
      .filter((f) => !this.agentFiles.has(resolve(this.gitRoot!, f)));
  }

  /** Resolves a shell path; undefined when it depends on unknown variables or substitutions. */
  private path(raw: string): string | undefined {
    let p = raw.replace(/^~(?=\/|$)/, this.home).replace(/^\$\{?HOME\}?(?=\/|$)/, this.home);
    p = p.replace(/\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?/g, (m, name) => this.vars.get(name) ?? m);
    if (p.includes("$") || (this.dir.includes("$") && !isAbsolute(p))) return;
    return resolve(this.dir, p);
  }
  private inside(p: string): boolean {
    const rel = relative(this.cwd, p);
    return !!rel && !rel.startsWith("..") && !isAbsolute(rel);
  }
  private scratch(p: string): boolean {
    return (
      ["/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"].includes(p) ||
      (p.startsWith(this.tmp + sep) && !(this.cwd + sep).startsWith(p + sep))
    );
  }
  private protectedPath(p: string): string | undefined {
    if (!this.inside(p)) return;
    for (const segment of relative(this.cwd, p).split(sep)) {
      for (const pattern of this.protectedPaths) {
        const re = new RegExp(
          "^" + pattern.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$",
        );
        if (re.test(segment)) return segment;
      }
    }
  }
  /** Classifies a write/delete target; `recursive` widens what counts as dangerous. */
  private target(raw: string, op: string, recursive: boolean): SafetyFinding | undefined {
    const p = this.path(raw);
    if (!p)
      return { rule: `${op}_unresolved_target`, verdict: recursive ? "block" : "ask", detail: `${op} sobre una ruta con variables o sustituciones (${raw}).` };
    if (!this.inside(p) && this.scratch(p)) return;
    if (!this.inside(p))
      return {
        rule: `${op}_outside_workspace`,
        verdict: "block",
        detail: p === this.cwd || relative(p, this.cwd).split(sep)[0] !== ".."
          ? `${op} sobre el workspace completo o un ancestro (${raw}).`
          : `${op} fuera del directorio de trabajo (${raw}).`,
      };
    const prot = this.protectedPath(p);
    if (prot)
      return { rule: `${op}_protected_path`, verdict: "block", detail: `${op} sobre una ruta protegida (${prot}).` };
    if (recursive && /[*?[]/.test(raw) && !raw.replace(/^\.\//, "").includes("/"))
      return { rule: `${op}_toplevel_glob`, verdict: "block", detail: `${op} recursivo con comodín en la raíz del workspace (${raw}).` };
    if (op === "delete" && !/[*?[]/.test(raw)) {
      const lost = this.untracked(p);
      if (lost.length)
        return {
          rule: "delete_untracked",
          verdict: "ask",
          detail: `Borra archivos sin versionar que git no puede recuperar (${lost.slice(0, 3).join(", ")}${lost.length > 3 ? ", …" : ""}). Si no los creaste tú en esta tarea, consérvalos o pregunta.`,
        };
    }
  }
  /** Reads a local script (≤64 KiB) so its commands get the same analysis as the command line. */
  private script(raw: string, depth: number, explicit = true): SafetyFinding[] {
    const p = this.path(raw);
    if (!p || !this.inside(p)) return [];
    let text: string;
    try {
      if (!statSync(p).isFile() || statSync(p).size > 65536) return [];
      text = readFileSync(p, "utf8");
    } catch {
      return [];
    }
    // Executed directly (./x): only shell scripts, by extension or shebang.
    if (!explicit && !/\.(sh|bash|zsh)$/.test(p) && !/^#!.*\b(ba|z|da|k)?sh\b/.test(text))
      return [];
    const dir = dirname(p);
    // Resolve the usual "directory of this script" idioms to a literal path.
    text = text
      .replace(/\$\(\s*dirname\s+"?\$\{?(0|BASH_SOURCE(\[0\])?)\}?"?\s*\)|`dirname\s+"?\$0"?`/g, dir)
      .replace(/\$\(\s*cd\s+"?([^"$()]+)"?\s*&&\s*pwd\s*\)/g, "$1");
    const saved = { dir: this.dir, vars: this.vars };
    this.dir = this.cwd;
    this.vars = new Map();
    const rel = relative(this.cwd, p);
    const findings = this.shell(text, depth + 1).map((f) => ({ ...f, detail: `script ${rel}: ${f.detail}` }));
    this.dir = saved.dir;
    this.vars = saved.vars;
    return findings;
  }
  private packageScript(name: string, depth: number): SafetyFinding[] {
    try {
      const pkg = JSON.parse(readFileSync(resolve(this.dir, "package.json"), "utf8"));
      const body = pkg?.scripts?.[name];
      if (typeof body !== "string") return [];
      return this.shell(body, depth + 1).map((f) => ({ ...f, detail: `npm run ${name}: ${f.detail}` }));
    } catch {
      return [];
    }
  }

  assess(action: Action): SafetyFinding[] {
    const input = action.input;
    if (action.toolName === "write" || action.toolName === "edit") {
      if (typeof input.path !== "string") return [];
      const f = this.target(input.path, action.toolName, false);
      return f ? [{ ...f, verdict: "block" }] : [];
    }
    if (action.toolName !== "bash" || typeof input.command !== "string") return [];
    return this.shell(input.command, 0);
  }

  private shell(text: string, depth: number): SafetyFinding[] {
    const findings: SafetyFinding[] = [];
    if (depth > 4)
      return [{ rule: "nested_shell", verdict: "ask", detail: "Anidamiento de shell demasiado profundo para analizar." }];
    if (/:\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:/.test(text))
      findings.push({ rule: "fork_bomb", verdict: "block", detail: "Fork bomb." });
    const outer = this.dir;
    for (const cmd of parseShell(text)) {
      for (const nested of cmd.nested) findings.push(...this.shell(nested, depth + 1));
      for (const r of cmd.redirects) {
        const f = this.target(r, "redirect", false);
        if (f) findings.push({ ...f, verdict: f.verdict === "ask" ? "ask" : "block" });
      }
      const assignments = cmd.words.filter((w) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(w));
      if (assignments.length === cmd.words.length)
        for (const a of assignments) {
          const [name, ...value] = a.split("=");
          const literal = value.join("=");
          // Values from substitutions or other variables stay unknown.
          if (literal.includes("$") || cmd.nested.length) this.vars.delete(name);
          else this.vars.set(name, literal);
        }
      const { words, sudo } = strip(cmd.words);
      if (sudo)
        findings.push({ rule: "privilege_escalation", verdict: "block", detail: "Escalada de privilegios (sudo/su/doas)." });
      if (!words.length) continue;
      const name = basename(words[0]);
      const args = words.slice(1);
      if (name === "cd" || name === "pushd") {
        const next = args.find((a) => a !== "--") ?? this.home;
        const p = next === "-" ? undefined : this.path(next);
        // Unknown destinations make every later relative path unresolvable.
        this.dir = p ?? "/$unknown";
        continue;
      }
      if (
        interpreters.includes(name) && cmd.pipedFrom &&
        ["curl", "wget"].includes(basename(strip(cmd.pipedFrom.words).words[0] ?? ""))
      )
        findings.push({ rule: "remote_code_execution", verdict: "block", detail: `Descarga canalizada a ${name}.` });
      if (interpreters.includes(name) && cmd.nested.some((n) => /\b(curl|wget)\b/.test(n)))
        findings.push({ rule: "remote_code_execution", verdict: "block", detail: `Código remoto ejecutado con ${name}.` });
      if ((shells.includes(name) || name === "eval") && (args.includes("-c") || name === "eval")) {
        const body = name === "eval" ? args.join(" ") : args[args.indexOf("-c") + 1];
        if (body) findings.push(...this.shell(body, depth + 1));
      } else if (shells.includes(name) || name === "source" || name === ".") {
        const file = args.find((a) => !a.startsWith("-"));
        if (file) findings.push(...this.script(file, depth));
      } else if (words[0].includes("/") && !isAbsolute(words[0])) {
        findings.push(...this.script(words[0], depth, false));
      }
      if (["npm", "pnpm", "yarn"].includes(name)) {
        const run = args[0] === "run" || args[0] === "run-script" ? args[1] : ["test", "start", "build"].includes(args[0]) ? args[0] : undefined;
        if (run) findings.push(...this.packageScript(run, depth));
      }
      findings.push(...this.command(name, args, text));
    }
    this.dir = outer;
    return findings;
  }

  private command(name: string, args: string[], text: string): SafetyFinding[] {
    const out: SafetyFinding[] = [];
    const flags = args.filter((a) => a.startsWith("-") && a !== "-" && a !== "--");
    const operands = (() => {
      const i = args.indexOf("--");
      return i < 0 ? args.filter((a) => !a.startsWith("-")) : [...args.slice(0, i).filter((a) => !a.startsWith("-")), ...args.slice(i + 1)];
    })();
    const short = (letter: string) => flags.some((f) => /^-[^-]/.test(f) && f.includes(letter));
    const long = (...names: string[]) => flags.some((f) => names.includes(f.split("=")[0]));
    const add = (rule: string, verdict: SafetyVerdict, detail: string) => out.push({ rule, verdict, detail });
    if (name.startsWith("mkfs")) add("disk_operation", "block", `Formatea un dispositivo (${name}).`);
    switch (name) {
      case "rm":
      case "rmdir":
      case "unlink":
      case "shred": {
        const recursive = short("r") || short("R") || long("--recursive") || name === "shred";
        for (const t of operands) {
          const f = this.target(t, "delete", recursive);
          if (f) out.push(f);
          else if (recursive && /^\.?\/?\.git(\/|$)/.test(t)) add("delete_git_dir", "block", "Borrado del repositorio git.");
        }
        if (!operands.length && name === "rm") add("delete_unknown_targets", "ask", "Borrado con objetivos desconocidos (p. ej. vía xargs).");
        break;
      }
      case "xargs":
        if (args.some((a) => ["rm", "shred", "unlink"].includes(basename(a))))
          add("delete_unknown_targets", "ask", "Borrado masivo a través de xargs.");
        break;
      case "find": {
        const deletes = args.includes("-delete") || args.some((a, i) => ["-exec", "-execdir", "-ok"].includes(a) && ["rm", "shred"].includes(basename(args[i + 1] ?? "")));
        if (deletes) {
          const roots = args.slice(0, Math.max(0, args.findIndex((a) => a.startsWith("-") || a === "(" || a === "!"))) ;
          for (const root of roots.length ? roots : ["."]) {
            const p = this.path(root);
            if (!p || (p !== this.cwd && !this.inside(p)))
              add("find_delete_outside", "block", `find con borrado fuera del workspace (${root}).`);
          }
          if (!out.length) add("find_delete", "ask", "find con borrado masivo dentro del workspace.");
        }
        break;
      }
      case "git": {
        let i = 0;
        while (i < args.length && args[i].startsWith("-")) i += ["-C", "-c", "--git-dir", "--work-tree"].includes(args[i]) ? 2 : 1;
        const sub = args[i];
        const rest = args.slice(i + 1);
        const has = (...xs: string[]) => rest.some((a) => xs.includes(a.split("=")[0]));
        const shortIn = (l: string) => rest.some((a) => /^-[^-]/.test(a) && a.includes(l));
        const all = (xs: string[]) => xs.some((a) => [".", ":/", "*", ":(top)"].includes(a));
        if (sub === "reset" && has("--hard", "--merge", "--keep"))
          add("git_discard_changes", "block", "git reset --hard descarta cambios sin commitear.");
        if (sub === "clean" && (shortIn("f") || has("--force")) && !(shortIn("n") || has("--dry-run")))
          add("git_clean", "block", "git clean borra archivos no rastreados.");
        if (sub === "checkout" && (all(rest) || has("--force") || (shortIn("f") && !shortIn("b"))))
          add("git_discard_changes", "block", "git checkout masivo descarta cambios sin commitear.");
        if (sub === "restore" && all(rest) && !(has("--staged", "-S") && !has("--worktree", "-W")))
          add("git_discard_changes", "block", "git restore masivo descarta cambios sin commitear.");
        if (sub === "stash" && ["drop", "clear"].includes(rest[0]))
          add("git_stash_drop", "block", "Elimina cambios guardados en el stash.");
        if (sub === "push") {
          if (has("--force", "--force-with-lease", "--mirror", "--delete") || shortIn("f") || shortIn("d") || rest.some((a) => a.startsWith("+") || a.startsWith(":")))
            add("git_force_push", "block", "Push forzado o borrado de ramas remotas.");
          else add("git_push", "ask", "Publica cambios en un remoto.");
        }
        if (sub === "branch" && (has("--delete") || shortIn("D") || shortIn("d")) && (shortIn("D") || has("--force")))
          add("git_branch_force_delete", "ask", "Borrado forzado de rama.");
        if (["filter-branch", "filter-repo", "replace"].includes(sub))
          add("git_rewrite_history", "block", "Reescritura de historia del repositorio.");
        if (sub === "rm" && (shortIn("r") || all(rest)) && !has("--cached"))
          add("git_rm_recursive", "block", "git rm recursivo borra archivos del árbol de trabajo.");
        break;
      }
      case "chmod":
      case "chown":
      case "chgrp": {
        const mode = name === "chmod" ? operands[0] : undefined;
        if (mode && (/^0?[0-7]?7[0-7]7$/.test(mode) || /(^|,)(a|o|ugo)?[+=][rwx]*w/.test(mode) && /^(a|o|ugo)/.test(mode)))
          add("permissions_world_writable", "block", `Permisos de escritura para todos (${mode}).`);
        const targets = name === "chmod" ? operands.slice(1) : operands.slice(1);
        for (const t of targets) {
          const p = this.path(t);
          if (!p || (p !== this.cwd && !this.inside(p))) add("permissions_outside", "block", `Cambio de permisos fuera del workspace (${t}).`);
        }
        if (name !== "chmod") add("ownership_change", "ask", "Cambio de propietario.");
        break;
      }
      case "dd": {
        const of = args.find((a) => a.startsWith("of="));
        if (of) {
          const f = this.target(of.slice(3), "write", false);
          if (f || of.startsWith("of=/dev/")) add("raw_device_write", "block", `dd escribe en ${of.slice(3)}.`);
        }
        break;
      }
      case "truncate":
        for (const t of operands) {
          const f = this.target(t, "write", false);
          if (f) out.push(f);
        }
        break;
      case "tee":
        for (const t of operands) {
          const f = this.target(t, "write", false);
          if (f) out.push({ ...f, verdict: "block" });
        }
        break;
      case "cp":
      case "mv":
      case "ln":
      case "install":
      case "rsync": {
        const dest = operands.at(-1);
        if (dest && operands.length > 1) {
          const f = this.target(dest, "write", false);
          if (f) out.push({ ...f, verdict: "block" });
        }
        if (name === "mv")
          for (const src of operands.slice(0, -1)) {
            const f = this.target(src, "delete", false);
            if (f) out.push(f);
          }
        if (name === "rsync" && long("--delete", "--delete-before", "--delete-after", "--remove-source-files"))
          add("rsync_delete", "ask", "rsync con borrado.");
        break;
      }
      case "curl":
      case "wget":
        if (long("--data", "--data-binary", "--data-raw", "--data-urlencode", "--form", "--upload-file", "--post-file", "--post-data", "--body-file") || args.some((a) => ["-d", "-F", "-T"].includes(a)) || (short("d") && name === "curl"))
          add("network_upload", "ask", `Envía datos a la red con ${name}.`);
        for (const [i, a] of args.entries())
          if (["-o", "--output", "-O", "--output-document"].includes(a) && args[i + 1] && args[i + 1] !== "-") {
            const f = this.target(args[i + 1], "write", false);
            if (f) out.push({ ...f, verdict: "block" });
          }
        break;
      case "fdisk":
      case "sfdisk":
      case "parted":
      case "gdisk":
      case "sgdisk":
      case "wipefs":
      case "mkswap":
      case "swapoff":
        add("disk_operation", "block", `Operación de disco (${name}).`);
        break;
      case "shutdown":
      case "reboot":
      case "poweroff":
      case "halt":
      case "init":
        add("system_power", "block", "Apagado o reinicio del sistema.");
        break;
      case "systemctl":
      case "service":
        if (args.some((a) => ["stop", "disable", "mask", "kill", "poweroff", "reboot", "halt", "isolate"].includes(a)))
          add("system_service", "block", "Detiene o deshabilita servicios del sistema.");
        break;
      case "kill":
      case "pkill":
      case "killall":
        add("process_kill", "ask", "Termina procesos que podrían no pertenecer a la tarea.");
        break;
      case "docker":
      case "podman": {
        const s = args.filter((a) => !a.startsWith("-"));
        if (["rm", "rmi", "kill"].includes(s[0]) || s.includes("prune") || (s[0] === "volume" && s[1] === "rm") || (s[0] === "compose" && s.includes("down") && (args.includes("-v") || args.includes("--volumes"))))
          add("container_destroy", "block", "Elimina contenedores, imágenes o volúmenes.");
        else if (["stop", "restart"].includes(s[0]) || (s[0] === "compose" && (s.includes("down") || s.includes("stop"))))
          add("container_stop", "ask", "Detiene contenedores existentes.");
        break;
      }
      case "npm":
      case "pnpm":
      case "yarn":
        if (args.some((a) => ["publish", "unpublish", "deprecate"].includes(a)))
          add("package_publish", "block", "Publica o retira paquetes de un registro.");
        else if (args.includes("-g") || args.includes("--global"))
          add("global_install", "ask", "Instalación global fuera del proyecto.");
        break;
      case "pip":
      case "pip3":
        if (args.includes("uninstall") || (args.includes("install") && !args.includes("--user") && !process.env.VIRTUAL_ENV))
          add("system_python_packages", "ask", "Modifica paquetes Python del sistema.");
        break;
      case "crontab":
        add("crontab", args.includes("-r") ? "block" : "ask", "Modifica tareas programadas.");
        break;
      case "psql":
      case "mysql":
      case "sqlite3":
      case "mongosh":
      case "mongo":
        if (/\b(drop\s+(table|database|schema|collection)|truncate\s+table|dropDatabase\s*\()/i.test(text) || /\bdelete\s+from\s+\w+\s*(;|$|["'])/i.test(text))
          add("database_destroy", "block", "Borrado masivo de datos en una base de datos.");
        break;
    }
    return out;
  }
}

export function assessSafety(
  action: Action,
  cwd: string,
  protectedPaths?: string[],
  agentFiles?: ReadonlySet<string>,
): SafetyFinding | undefined {
  const findings = new SafetyGuard(resolve(cwd), protectedPaths, agentFiles).assess(action);
  return findings.find((f) => f.verdict === "block") ?? findings[0];
}

// Concrete safe alternatives: small models recover better with a next step than with a "no".
const alternatives: Record<string, string> = {
  git_discard_changes: "Para descartar cambios de archivos concretos usa `git restore <archivo>` o `git checkout -- <archivo>`; los archivos sin versionar no se tocan.",
  git_clean: "Revisa `git status` y borra solo los archivos concretos que la tarea pida.",
  delete_untracked: "Bórralos solo si los creaste tú en esta tarea; si no, consérvalos o muévelos a una carpeta de respaldo dentro del proyecto.",
  delete_toplevel_glob: "Nombra explícitamente los archivos o directorios a borrar.",
  delete_unresolved_target: "Sustituye la variable por una ruta literal dentro del proyecto y comprueba que no quede vacía.",
  permissions_world_writable: "Usa permisos mínimos, p. ej. `chmod +x <script>` o `chmod 755 <script>`.",
  remote_code_execution: "No ejecutes código descargado; lee el script y aplica solo los pasos necesarios.",
  privilege_escalation: "Trabaja sin privilegios dentro del proyecto o pide al usuario que lo haga.",
};
export function safetyReason(f: SafetyFinding): string {
  const alt = alternatives[f.rule] ?? (f.rule.endsWith("_outside_workspace") ? "Trabaja solo con rutas dentro del proyecto." : "");
  return f.verdict === "block"
    ? `Acción bloqueada por seguridad (${f.rule}): ${f.detail} ${alt} No la reformules para eludir el control; usa una alternativa acotada a la tarea o explica al usuario por qué es necesaria.`
    : `Acción retenida por seguridad (${f.rule}): ${f.detail} ${alt} Requiere confirmación del usuario; si no es imprescindible, usa una alternativa acotada a la tarea.`;
}
