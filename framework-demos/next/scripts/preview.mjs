import {createServer} from "node:http"
import {readFile, stat} from "node:fs/promises"
import {extname, resolve, sep} from "node:path"
import {fileURLToPath} from "node:url"
import {parseArgs} from "node:util"

const {values} = parseArgs({options: {port: {type: "string"}}})
const port = Number(values.port ?? process.env.PORT ?? 4173)
const root = fileURLToPath(new URL("../out/", import.meta.url)).replace(/\/$/, "")
const assetPrefix = (process.env.BOKEH_DEMO_BASE ?? "").replace(/\/+$/, "")
const types = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8",
}

const server = createServer(async (request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, {Allow: "GET, HEAD"})
    response.end()
    return
  }
  try {
    let path = decodeURIComponent(new URL(request.url, "http://localhost").pathname)
    if (assetPrefix && path.startsWith(`${assetPrefix}/`)) path = path.slice(assetPrefix.length)
    let file = resolve(root, `.${path}`)
    if (file !== root && !file.startsWith(`${root}${sep}`)) throw new Error("Not found")
    if ((await stat(file)).isDirectory()) file = resolve(file, "index.html")
    const body = await readFile(file)
    response.writeHead(200, {"Content-Type": types[extname(file)] ?? "application/octet-stream", "Cache-Control": "no-store"})
    response.end(request.method === "HEAD" ? undefined : body)
  } catch {
    response.writeHead(404, {"Content-Type": "text/plain; charset=utf-8"})
    response.end(request.method === "HEAD" ? undefined : "Not found")
  }
})

server.listen(port, "127.0.0.1", () => console.log(`Next.js preview: http://127.0.0.1:${port}/`))
