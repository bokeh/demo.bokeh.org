import {svelte} from "@sveltejs/vite-plugin-svelte"
import {defineConfig} from "vite"

export default defineConfig({
  base: process.env.BOKEH_DEMO_BASE ?? "/",
  plugins: [svelte({configFile: false})],
})
