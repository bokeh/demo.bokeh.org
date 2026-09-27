# Bokeh with Next.js

A standalone Next.js App Router example with an interactive wave field and a linked
cross section. Native React controls update Bokeh models; the two Bokeh roots sit in
separate parts of the page's HTML layout.

Copy this entire directory to run it independently. It includes the package manifest,
lockfile, plot models, styles, page content, and build configuration. It does not need
Python, a Bokeh server, or any files from the rest of the demo repository.

## Run locally

Use Node.js 24 or newer and pnpm 11.25.0. From this directory:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open <http://127.0.0.1:3000>. To validate and preview the static export:

```sh
pnpm check
pnpm build
pnpm preview
```

The preview is served at <http://127.0.0.1:4173>. Set another port with
`pnpm preview --port 4180`. The check command generates Next.js route types before
running TypeScript, so it also works before the first build.

## How embedding works

[`app/page.tsx`](app/page.tsx) is a server component that supplies serializable initial
parameters at build time. [`app/WaveLab.tsx`](app/WaveLab.tsx) is a client component that
creates the Bokeh models once and manages the controls, animation, and conditional
cross section. The React adapter supplies the document and root components:

```tsx
"use client"
import {BokehDocument, BokehRoot} from "@bokeh/react"

<BokehDocument models={dashboard.models}>
  <section><BokehRoot model={dashboard.field}/></section>
  <aside><BokehRoot model={dashboard.profile}/></aside>
</BokehDocument>
```

[`src/waves.ts`](src/waves.ts) creates the image, line plot, and linked data sources.
`app/chrome.json` contains the demo site's header, footer, introduction, and short code
example. Styles and the favicon are included in `public/assets/`.

## Deploy

`pnpm build` exports the application to `out/`. Publish that directory with a static
web server; no Next.js or Node.js server is required in production.

By default, assets are served from the site's root. The Bokeh demo site's build sets
`BOKEH_DEMO_BASE=/assets/frameworks/nextjs` to put this app's assets under a dedicated
prefix while serving its HTML at `/nextjs`. If you use this option, your host must
serve the exported assets at the chosen prefix. Use the same environment variable
with `pnpm preview` to preview that build locally.

BokehJS and the React adapter are pinned to the matching `4.0.0-dev.5` npm release.
The local pnpm configuration allows those prereleases through pnpm's release-age
check. Update both direct Bokeh packages together when changing versions.
