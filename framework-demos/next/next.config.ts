import type {NextConfig} from "next"

const config: NextConfig = {
  output: "export",
  agentRules: false,
  outputFileTracingRoot: import.meta.dirname,
  turbopack: {root: import.meta.dirname},
  assetPrefix: (process.env.BOKEH_DEMO_BASE ?? "").replace(/\/+$/, ""),
  trailingSlash: true,
  poweredByHeader: false,
}
export default config
