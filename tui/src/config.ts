import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const SIERRA_DIR = path.resolve(__dirname, "..", "..");
export const LAUNCH_CWD =
  process.env.SIERRA_WORKSPACE || process.env.INIT_CWD || process.cwd();
export const VENV_PYTHON =
  process.platform === "win32"
    ? path.join(SIERRA_DIR, ".venv", "Scripts", "python.exe")
    : path.join(SIERRA_DIR, ".venv", "bin", "python");
