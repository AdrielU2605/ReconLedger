import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without `test.globals: true` in vite.config.ts, Testing Library's
// auto-registered cleanup (which relies on a global `afterEach`) never
// fires, so unmounted components from earlier tests in the same file
// silently accumulate in the DOM and queries start matching duplicates.
afterEach(() => {
  cleanup();
});
