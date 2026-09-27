import {spawnSync} from "node:child_process"
import {cp, mkdtemp, rm} from "node:fs/promises"
import {tmpdir} from "node:os"
import {basename, resolve} from "node:path"
import {fileURLToPath} from "node:url"

const root = fileURLToPath(new URL("../", import.meta.url))
// Outside the checkout so Node cannot resolve an undeclared parent dependency.
const temporary = await mkdtemp(resolve(tmpdir(), "bokeh-standalone-"))
const env = {...process.env, NEXT_TELEMETRY_DISABLED: "1"}
delete env.BOKEH_DEMO_BASE
const ignored = new Set(["node_modules", "dist", "out", ".next", "next-env.d.ts", "tsconfig.tsbuildinfo"])

function run(command, args, cwd, variables = env) {
  const result = spawnSync(command, args, {cwd, env: variables, stdio: "inherit"})
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} failed in ${cwd}`)
}

try {
  for (const [index, app] of ["react", "vue", "svelte", "components", "next"].entries()) {
    const directory = resolve(temporary, "work", app)
    await cp(resolve(root, app), directory, {recursive: true, filter: (path) => !ignored.has(basename(path))})
    console.log(`Checking independent ${app} copy: ${directory}`)
    run("pnpm", ["install", "--frozen-lockfile"], directory)
    run("pnpm", ["run", "check"], directory)
    run("pnpm", ["run", "build"], directory)

    run(process.execPath, [resolve(root, "node_modules/@playwright/test/cli.js"), "test"], root, {
      ...env,
      BOKEH_TEST_URL: `http://127.0.0.1:${4310 + index}`,
      BOKEH_STANDALONE: app === "next" ? "nextjs" : app,
      BOKEH_STANDALONE_DIRECTORY: directory,
    })
  }
} finally {
  await rm(temporary, {recursive: true, force: true})
}
