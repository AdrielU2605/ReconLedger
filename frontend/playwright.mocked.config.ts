import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Same Windows-Store-Python-stub workaround as playwright.config.ts.
function backendPythonCommand(): string {
  const winVenv = "../backend/.venv/Scripts/python.exe";
  const posixVenv = "../backend/.venv/bin/python";
  if (process.platform === "win32" && existsSync(winVenv)) return ".venv\\Scripts\\python.exe";
  if (existsSync(posixVenv)) return ".venv/bin/python";
  return process.platform === "win32" ? "python" : "python3";
}

/**
 * CP9 (PRD 10.1): happy path, partial-provider failure, cached rerun, diff,
 * history reopen, keyboard navigation, theme, and the three downloads - all
 * against a scripted (mocked) OutboundGateway for deterministic, CI-safe
 * runs. Deliberately separate from playwright.config.ts, which runs the
 * single UX-12 client-isolation check against the real production gateway -
 * the two can't share a webServer since one needs genuine provider traffic
 * and the other needs repeatable data, and both bind the backend to the
 * same port, so they're never run in the same `playwright test` invocation.
 */
export default defineConfig({
  testDir: "./e2e-mocked",
  timeout: 30_000,
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
      command: `${backendPythonCommand()} scripts/run_e2e_server_mocked.py`,
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
