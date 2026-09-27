import {spawnSync} from "node:child_process"

const args = process.argv.slice(2)
if (args.length === 0) throw new Error("Supply a pnpm command to run in each app")
for (const app of ["react", "vue", "svelte", "components", "next"]) {
  const result = spawnSync("pnpm", args, {cwd: new URL(`../${app}/`, import.meta.url), stdio: "inherit"})
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
