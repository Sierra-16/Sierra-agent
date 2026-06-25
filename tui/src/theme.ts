/**
 * Sierra TUI Theme — ink compatible Color types.
 * Uses hex colors for precision, ansi:xxx for named colors.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyColor = any;
export interface Theme {
  color: {
    primary: AnyColor;
    accent: AnyColor;
    border: AnyColor;
    text: AnyColor;
    muted: AnyColor;
    label: AnyColor;
    ok: AnyColor;
    error: AnyColor;
    warn: AnyColor;
    prompt: AnyColor;
    userMsg: AnyColor;
    assistantMsg: AnyColor;
    systemMsg: AnyColor;
    gem: AnyColor;
    leaf: AnyColor;
    gold: AnyColor;
    panel: AnyColor;
    logo: AnyColor[];
  };
  brand: {
    name: string;
    prompt: string;
    welcome: string;
    goodbye: string;
  };
}

export const SIERRA_THEME = {
  color: {
    primary: "#7ddf64",
    accent: "#2dd4bf",
    border: "#3f4f46",
    text: "#e5e7eb",
    muted: "#8b9b91",
    label: "#a3b18a",
    ok: "#86efac",
    error: "#fb7185",
    warn: "#facc15",
    prompt: "#86efac",
    userMsg: "#67e8f9",
    assistantMsg: "#d9f99d",
    systemMsg: "#fcd34d",
    gem: "#38bdf8",
    leaf: "#86efac",
    gold: "#facc15",
    panel: "#26362f",
    logo: ["#d9f99d", "#bef264", "#86efac", "#4ade80", "#2dd4bf", "#38bdf8"],
  },
  brand: {
    name: "Sierra AI",
    prompt: "❯",
    welcome: "输入问题，或键入 /help 查看命令",
    goodbye: "Goodbye!",
  },
};

const G = "█";
export const SIERRA_LOGO = [
  ` ${G}${G}${G}${G}${G}${G}${G}╗${G}${G}╗${G}${G}${G}${G}${G}${G}${G}╗${G}${G}${G}${G}${G}${G}╗ ${G}${G}${G}${G}${G}${G}╗  ${G}${G}${G}${G}${G}╗`,
  ` ${G}${G}╔════╝${G}${G}║${G}${G}╔════╝${G}${G}╔══${G}${G}╗${G}${G}╔══${G}${G}╗${G}${G}╔══${G}${G}╗`,
  ` ${G}${G}${G}${G}${G}${G}${G}╗${G}${G}║${G}${G}${G}${G}${G}╗  ${G}${G}${G}${G}${G}${G}╔╝${G}${G}${G}${G}${G}${G}╔╝${G}${G}${G}${G}${G}${G}${G}║`,
  ` ╚════${G}${G}║${G}${G}║${G}${G}╔══╝  ${G}${G}╔══${G}${G}╗${G}${G}╔══${G}${G}╗${G}${G}╔══${G}${G}║`,
  ` ${G}${G}${G}${G}${G}${G}${G}║${G}${G}║${G}${G}${G}${G}${G}${G}${G}${G}╗${G}${G}║  ${G}${G}║${G}${G}║  ${G}${G}║${G}${G}║  ${G}${G}║`,
  ` ╚══════╝╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝`,
];
export const LOGO_WIDTH = 56;
