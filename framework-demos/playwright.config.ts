import {defineConfig} from "@playwright/test"

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  workers: 3,
  timeout: 30_000,
  use: {baseURL: "http://127.0.0.1:4173", viewport: {width: 1440, height: 1100}, trace: "retain-on-failure"},
  webServer: {command: "node scripts/preview.mjs", url: "http://127.0.0.1:4173/react", reuseExistingServer: !process.env.CI},
})
