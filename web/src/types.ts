import type { Component } from "vue";

export type ViewId =
  | "chat"
  | "sessions"
  | "memory"
  | "tools"
  | "skills"
  | "mcp"
  | "integrations"
  | "cron"
  | "audit";

export type NavItem = {
  id: ViewId;
  label: string;
  subtitle: string;
  icon: Component;
};

export type DashboardPayload = {
  generated_at: string;
  identity: Record<string, any>;
  usage: Record<string, any>;
  conversation: Record<string, any>;
  tools: Record<string, any>;
  memory: Record<string, any>;
  mcp: Record<string, any>;
  tasks: Record<string, any>;
  background: Record<string, any>;
  cron: Record<string, any>;
  skills: Record<string, any>;
  context: Record<string, any>;
  audit: Record<string, any>;
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user" | "system";
  text: string;
};

export type ChatActivityStatus = "active" | "done" | "error" | "muted";

export type ChatActivityEvent = {
  id: string;
  type: string;
  label: string;
  detail?: string;
  status: ChatActivityStatus;
  toolName?: string;
  approvalId?: string;
  inputId?: string;
  risk?: string;
  reason?: string;
  arguments?: string;
  progress?: number;
  decision?: "once" | "session" | "deny" | string;
  question?: string;
  options?: Array<{
    label: string;
    value?: string;
    description?: string;
  }>;
  allowFreeText?: boolean;
};

export type SessionSummary = {
  id: string;
  title?: string;
  updated?: string | number;
  created?: string | number;
  [key: string]: any;
};

export function compactPath(path: string | undefined) {
  if (!path) {
    return "not set";
  }
  const normalized = String(path).replace(/\\/g, "/");
  const parts = normalized.split("/");
  if (parts.length <= 3) {
    return path;
  }
  return `${parts[0]}/.../${parts.slice(-2).join("/")}`;
}

export function formatTimestamp(value: any) {
  if (!value) {
    return "unknown";
  }
  if (typeof value === "number") {
    return new Date(value * 1000).toLocaleString();
  }
  return formatTime(value);
}

export function formatTime(value: any) {
  if (!value) {
    return "unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function safeArray<T = any>(value: any): T[] {
  return Array.isArray(value) ? value : [];
}
