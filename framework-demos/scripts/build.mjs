import {cp, mkdir, rm} from "node:fs/promises"
import {spawnSync} from "node:child_process"
import {fileURLToPath} from "node:url"
import {resolve} from "node:path"

const root = fileURLToPath(new URL("../", import.meta.url))
const output = resolve(root, "../site/frameworks")
await rm(output, {recursive: true, force: true})
await mkdir(output, {recursive: true})

for (const app of ["react", "vue", "svelte", "components", "next"]) {
  const route = app === "next" ? "nextjs" : app
  const result = spawnSync("npm", ["run", "build"], {
    cwd: resolve(root, app),
    stdio: "inherit",
    env: {...process.env, BOKEH_DEMO_BASE: `/assets/frameworks/${route}/`, NEXT_TELEMETRY_DISABLED: "1"},
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
  await cp(resolve(root, app, app === "next" ? "out" : "dist"), resolve(output, route), {recursive: true})
}
console.log("Built five standalone framework apps in site/frameworks/.")
