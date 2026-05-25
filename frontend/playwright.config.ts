import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // SSE streaming tests must not saturate the rate limiter
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: 1,
  reporter: "list",
  timeout: 90_000, // Azure roundtrip + gpt-4o streaming; allow extra for retries
  expect: {
    timeout: 35_000,
  },
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Assumes both frontend (3000) and backend (8000) are already running.
  // Start them separately before running E2E tests.
});
