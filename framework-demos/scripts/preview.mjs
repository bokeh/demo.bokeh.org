import {createServer} from "node:http"
import {readFile, stat} from "node:fs/promises"
import {resolve, extname, sep} from "node:path"
import {fileURLToPath} from "node:url"

const site = resolve(fileURLToPath(new URL("../../site/", import.meta.url)))
const types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2"}
const routes = new Set(["react", "vue", "svelte", "components", "nextjs"])
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, "http://localhost").pathname)
    const route = path.replace(/^\/+|\/+$/g, "").replace(/^next\.js$/, "nextjs")
    const relative = routes.has(route) ? `frameworks/${route}/index.html` : path.startsWith("/assets/") ? path.slice(8) : "404.html"
    const file = resolve(site, relative)
    if (!file.startsWith(site + sep) || !(await stat(file)).isFile()) throw new Error("Not found")
    const body = await readFile(file)
    response.writeHead(relative === "404.html" ? 404 : 200, {"Content-Type": types[extname(file)] ?? "application/octet-stream", "Cache-Control": "no-store"})
    response.end(request.method === "HEAD" ? undefined : body)
  } catch {
    response.writeHead(404)
    response.end("Not found")
  }
})
server.listen(Number(process.env.PORT ?? 4173), "127.0.0.1", () => console.log("Framework preview: http://127.0.0.1:4173/react"))
