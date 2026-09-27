import {defineConfig} from "vite"

export default defineConfig({
  base: process.env.BOKEH_DEMO_BASE ?? "/",
})
