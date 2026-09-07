import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Bare "python"/"python3" on Windows can resolve to a sandboxed Microsoft
// Store stub with no real filesystem access, so a local dev venv's own
// interpreter must be invoked explicitly rather than relied on via PATH.
// CI has no venv at all (the backend CI job installs straight into the
// runner's system Python), so fall back to plain "python" there.
function backendPythonCommand(): string {
  const winVenv = "../backend/.venv/Scripts/python.exe";
  const posixVenv = "../backend/.venv/bin/python";
  if (process.platform === "win32" && existsSync(winVenv)) return ".venv\\Scripts\\python.exe";
  if (existsSync(posixVenv)) return ".venv/bin/python";
  return process.platform === "win32" ? "python" : "python3";
}

/**
 * CP8 scope: a single UX-12 client-isolation check, run against the real
 * production gateway (a throwaway SQLite DB, not the developer's own) so it
 * proves the browser's behavior against genuine archived/registry evidence,
 * not a scripted stand-in. CP9 adds the full happy-path/partial-failure/
 * cached-rerun/diff/keyboard/theme/downloads suite described in PRD 10.1 -
 * those scenarios need deterministic (mocked-gateway) backend responses to
 * be reliable on every run, which is a separate webServer/app configuration
 * from this one.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${backendPythonCommand()} scripts/run_e2e_server.py`,
      cwd: "../backend",
      url: "http://127.0.0.1:8000/health",
      timeout: 30_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      timeout: 30_000,
      reuseExistingServer: false,
    },
  ],
});
