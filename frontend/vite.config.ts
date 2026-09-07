import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Same-origin from the browser's point of view during dev, so the SSE
      // stream and every fetch avoid CORS entirely; the backend's own
      // CORSMiddleware (ALLOWED_FRONTEND_ORIGINS) is the fallback for anyone
      // hitting the API directly without this proxy.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // e2e/ holds Playwright specs (npm run test:e2e), not Vitest ones - both
    // frameworks default to globbing *.spec.ts, so without this exclusion
    // Vitest tries to load Playwright's test() and fails immediately.
    // Extends (not replaces) Vitest's own default exclude list.
    exclude: [...configDefaults.exclude, "e2e/**"],
    // Without this, a vi.fn() call count (or mockResolvedValue override)
    // from one test silently carries into the next test in the same file -
    // exactly the kind of cross-test pollution that produces flaky,
    // order-dependent failures.
    clearMocks: true,
  },
});
