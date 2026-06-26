import { spawn, ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";

export interface TaskStep {
  id: string;
  position: number;
  step: string;
  status: "pending" | "in_progress" | "completed";
  note?: string;
}

export interface TaskExecution {
  id: string;
  tool_call_id: string;
  tool_name: string;
  risk: string;
  status: "uncertain";
}

export interface TaskPlan {
  id: string;
  conversation_id: string;
  objective: string;
  explanation?: string;
  status: "active" | "interrupted" | "completed" | "cancelled";
  current_step_id?: string | null;
  steps: TaskStep[];
  uncertain_executions?: TaskExecution[];
}

export interface SkillSummary {
  name: string;
  description: string;
  category: string;
  triggers?: string[];
  platforms?: string[];
  prerequisites?: Record<string, unknown>;
  resource_counts?: Record<string, number>;
  offered?: boolean;
  readiness_status?: string;
  readiness_reason?: string | null;
  missing_required_commands?: string[];
  missing_required_environment_variables?: string[];
}

export interface ServerEvent {
  type: string;
  text?: string;
  name?: string;
  id?: string;
  risk?: string;
  reason?: string;
  arguments?: string;
  approved?: boolean;
  decision?: "once" | "session" | "deny";
  question?: string;
  options?: { label: string; description?: string; value?: string }[];
  allow_free_text?: boolean;
  value?: string;
  label?: string;
  free_text?: boolean;
  cancelled?: boolean;
  count?: number;
  before_tokens?: number;
  after_tokens?: number;
  summarized_messages?: number;
  kept_messages?: number;
  success?: boolean;
  available?: boolean;
  summary?: Record<string, unknown>;
  key?: string;
  title?: string;
  model?: string;
  cwd?: string;
  recent?: { id: string; title: string } | null;
  companion_hint?: string;
  convs?: { id: string; title: string }[];
  sessions?: {
    id: string;
    title?: string;
    updated_at?: number;
    message_count?: number;
  }[];
  results?: {
    message_id?: number;
    session_id: string;
    role: string;
    snippet?: string;
    content?: string;
    created_at?: number;
    title?: string;
  }[];
  models?: { key: string; name: string; active?: boolean }[];
  skills?: SkillSummary[];
  errors?: string[];
  reloaded?: boolean;
  records?: {
    timestamp?: string;
    tool?: string;
    decision?: string;
    success?: boolean;
    executed?: boolean;
    duration_ms?: number;
  }[];
  active?: string;
  action?: "resume" | "abandon";
  task?: TaskPlan | null;
  recovery_task?: TaskPlan | null;
  status?: {
    servers?: {
      name: string;
      status: string;
      transport?: string;
      enabled: boolean;
      tools: number;
      error?: string;
      command?: string;
      url?: string;
    }[];
    tools?: string[];
  };
  messages?: { role: string; text: string }[];
  usage?: {
    input: number;
    output: number;
    context: number;
    context_window: number;
    context_estimated: boolean;
  };
}

export class Gateway extends EventEmitter {
  private proc: ChildProcess | null = null;
  private buffer = "";
  private startArgs: { pythonPath: string; cwd: string; workspaceCwd: string } | null = null;
  private interrupting = false;
  private discardOutput = false;
  private queuedMessages: Record<string, unknown>[] = [];

  start(pythonPath: string, cwd: string, workspaceCwd: string): void {
    this.startArgs = { pythonPath, cwd, workspaceCwd };
    this.discardOutput = false;
    const serverScript = "run_server.py";
    this.proc = spawn(pythonPath, [serverScript], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
        SIERRA_WORKSPACE: workspaceCwd,
      },
    });

    this.proc.on("error", () => {});

    this.proc.stdout?.on("data", (chunk: Buffer) => {
      if (this.discardOutput) return;
      this.buffer += chunk.toString();
      const lines = this.buffer.split("\n");
      this.buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const ev: ServerEvent = JSON.parse(line);
          this.emit("event", ev);
        } catch {}
      }
    });

    this.proc.stderr?.on("data", (chunk: Buffer) => {
      if (this.discardOutput) return;
      process.stderr.write(chunk);
    });

    this.proc.on("exit", () => {
      this.proc = null;
      this.buffer = "";
      if (this.interrupting) {
        this.interrupting = false;
        const args = this.startArgs;
        if (args) {
          this.start(args.pythonPath, args.cwd, args.workspaceCwd);
        }
        this.flushQueue();
        this.emit("interrupted");
        return;
      }
      this.emit("exit");
    });
  }

  send(msg: Record<string, unknown>): void {
    if (!this.interrupting && !this.discardOutput && this.proc?.stdin?.writable) {
      this.proc.stdin.write(JSON.stringify(msg) + "\n", "utf-8");
      return;
    }
    this.queuedMessages.push(msg);
  }

  stop(): void {
    if (this.proc) {
      this.send({ cmd: "quit" });
      setTimeout(() => this.killProcessTree(), 500);
    }
  }

  interrupt(): void {
    if (this.proc) {
      this.interrupting = true;
      this.discardOutput = true;
      this.emit("interrupting");
      this.killProcessTree();
    }
  }

  forceStop(): void {
    if (this.proc) {
      this.killProcessTree();
    }
  }

  private flushQueue(): void {
    const queued = this.queuedMessages.splice(0);
    for (const msg of queued) {
      this.send(msg);
    }
  }

  private killProcessTree(): void {
    const pid = this.proc?.pid;
    if (!this.proc || !pid) return;
    if (process.platform === "win32") {
      const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
      });
      killer.on("error", () => this.proc?.kill());
      return;
    }
    this.proc.kill("SIGKILL");
  }
}
