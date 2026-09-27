import {readFileSync} from "node:fs"
import {fileURLToPath} from "node:url"

const site = new URL("../../site/", import.meta.url)
export const header = readFileSync(new URL("header.html.jinja", site), "utf8")
export const footer = readFileSync(new URL("footer.html.jinja", site), "utf8")
export const root = fileURLToPath(new URL("../", import.meta.url))
const wave = {
  title: "Where waves meet",
  description: "Two sources, one interference field. Tune their rhythm and watch bands of constructive and destructive interference take shape.",
  domain: "Waves · images · animation",
}
export const demos = {
  react: {...wave, framework: "React", feature: "React state & shared roots"},
  vue: {...wave, framework: "Vue", feature: "Vue reactivity & Teleport"},
  svelte: {...wave, framework: "Svelte", feature: "Svelte runes & actions"},
  components: {...wave, framework: "Web Components", feature: "Custom elements & independent roots"},
  nextjs: {...wave, framework: "Next.js", feature: "App Router · static export · client components"},
}

export function intro(key) {
  const demo = demos[key]
  const directory = key === "nextjs" ? "next" : `src/${key}`
  return `<section class="application-intro"><div><p class="section-kicker"><span></span>${demo.framework} + Bokeh</p><h1>${demo.title}</h1><p>${demo.description}</p></div><div class="application-meta"><p>${demo.domain}<br><span>Standalone BokehJS · 4.0.0-dev.5</span></p><span class="framework-tag">${demo.feature}</span><div class="application-links"><a href="https://github.com/bokeh/demo.bokeh.org/tree/main/framework-demos/${directory}">View full app source <span aria-hidden="true">↗</span></a></div></div></section>`
}

const snippets = {
  react: `import {BokehDocument, BokehRoot} from "@bokeh/react"

<BokehDocument models={dashboard.models}>
  <section><BokehRoot model={dashboard.field}/></section>
  <aside><BokehRoot model={dashboard.profile}/></aside>
</BokehDocument>`,
  vue: `import {BokehDocument, BokehRoot} from "@bokeh/vue"

<BokehDocument :models="dashboard.models">
  <section><BokehRoot :model="dashboard.field" /></section>
  <aside><BokehRoot :model="dashboard.profile" /></aside>
</BokehDocument>`,
  svelte: `import {bokehDocument, bokehRoot} from "@bokeh/svelte"

<div use:bokehDocument={{models: dashboard.models}}>
  <section use:bokehRoot={{model: dashboard.field}}></section>
  <aside use:bokehRoot={{model: dashboard.profile}}></aside>
</div>`,
  components: `import {defineBokehDocumentElement, defineBokehRootElement}
  from "@bokeh/web-component"
defineBokehDocumentElement()
defineBokehRootElement()

<bokeh-document id="plots">
  <bokeh-root id="field"></bokeh-root>
</bokeh-document>
<aside><bokeh-root id="profile"></bokeh-root></aside>

provider.models = dashboard.models
fieldRoot.model = dashboard.field
profileRoot.bokehDocument = provider
profileRoot.model = dashboard.profile`,
  nextjs: `"use client"
import {BokehDocument, BokehRoot} from "@bokeh/react"

<BokehDocument models={dashboard.models}>
  <section><BokehRoot model={dashboard.field}/></section>
  <aside><BokehRoot model={dashboard.profile}/></aside>
</BokehDocument>`,
}

export function embedExample(key) {
  const escaped = snippets[key].replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  return `<section class="embed-example" aria-label="Framework embedding example"><div><p class="eyebrow">Framework adapter</p><h2>Embed Bokeh in ${demos[key].framework}</h2><p>Mount two Bokeh plots or tables in separate page elements. See the full app source for model creation, data and controls.</p></div><pre><code>${escaped}</code></pre></section>`
}

export function html(key, entry) {
  const demo = demos[key]
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow"><title>${demo.title} · ${demo.framework} · Bokeh demos</title><meta name="description" content="${demo.description}"><link rel="icon" href="/assets/bokeh-icon.svg?v=2" type="image/svg+xml"><link rel="stylesheet" href="/assets/site.css?v=14"><link rel="stylesheet" href="/assets/frameworks/frameworks.css"></head><body>${header}<main class="application-page framework-page" id="main-content">${intro(key)}<div id="framework-app"><p class="framework-loading" role="status">Loading interactive demo…</p></div><noscript><p>Enable JavaScript to explore this interactive demo.</p></noscript>${embedExample(key)}<p class="session-note">Computed, synthetic data. All interactions run in your browser.</p></main>${footer}<script type="module" src="${entry}"></script></body></html>`
}
