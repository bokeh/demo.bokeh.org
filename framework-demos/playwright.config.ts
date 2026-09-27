import {defineConfig} from "@playwright/test"

const standaloneDirectory = process.env.BOKEH_STANDALONE_DIRECTORY
const testURL = process.env.BOKEH_TEST_URL ?? "http://127.0.0.1:4173"

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  workers: 3,
  timeout: 30_000,
  use: {baseURL: testURL, viewport: {width: 1440, height: 1100}, trace: "retain-on-failure"},
  webServer: standaloneDirectory ? {
    command: `pnpm run preview --port ${new URL(testURL).port}${process.env.BOKEH_STANDALONE === "nextjs" ? "" : " --strictPort"}`,
    cwd: standaloneDirectory,
    url: testURL,
    reuseExistingServer: false,
  } : process.env.BOKEH_TEST_URL ? undefined : {
    command: "node scripts/preview.mjs", url: "http://127.0.0.1:4173/react", reuseExistingServer: !process.env.CI,
  },
})
