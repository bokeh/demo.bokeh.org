import {cp, mkdir, rm, writeFile} from "node:fs/promises"
import {spawnSync} from "node:child_process"
import {resolve} from "node:path"
import {build} from "vite"
import vue from "@vitejs/plugin-vue"
import {svelte} from "@sveltejs/vite-plugin-svelte"
import {html, root, header, footer, intro, embedExample} from "./shell.mjs"

const output = resolve(root, "../site/frameworks")
await rm(output, {recursive: true, force: true})
const inputs = {}
for (const name of ["react", "vue", "svelte", "components"]) {
  const directory = resolve(root, "work", name)
  await mkdir(directory, {recursive: true})
  const entry = name === "react" ? "main.tsx" : "main.ts"
  const file = resolve(directory, "index.html")
  await writeFile(file, html(name, `../../src/${name}/${entry}`))
  inputs[name] = file
}
await build({
  root: resolve(root, "work"), base: "/assets/frameworks/",
  plugins: [vue(), svelte({configFile: false})],
  esbuild: {jsx: "automatic"},
  build: {outDir: output, emptyOutDir: true, rollupOptions: {input: inputs}},
})
await cp(resolve(root, "src/shared/frameworks.css"), resolve(output, "frameworks.css"))
await writeFile(resolve(root, "work/chrome.json"), JSON.stringify({header, footer, intro: intro("nextjs"), embedExample: embedExample("nextjs")}))
const next = spawnSync(process.execPath, [resolve(root, "node_modules/next/dist/bin/next"), "build", "--webpack"], {
  cwd: resolve(root, "next"), stdio: "inherit", env: {...process.env, NEXT_TELEMETRY_DISABLED: "1"},
})
if (next.status !== 0) process.exit(next.status ?? 1)
await cp(resolve(root, "next/out"), resolve(output, "nextjs"), {recursive: true})
console.log("Built five isolated framework demos in site/frameworks/.")
