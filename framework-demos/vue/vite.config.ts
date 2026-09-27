import vue from "@vitejs/plugin-vue"
import {defineConfig} from "vite"

export default defineConfig({
  base: process.env.BOKEH_DEMO_BASE ?? "/",
  plugins: [vue()],
})
