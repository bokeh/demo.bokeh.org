# React + Bokeh: Where waves meet

A complete React application with two Bokeh plots, native HTML controls, and a
wave interference simulation. Copy this directory anywhere and run it on its
own; it does not import files from the demo site or another example.

## Run

Install Node.js 24 or newer and pnpm 11.25.0, then run from this directory:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open the local URL printed by Vite. To check, build, and preview the production
files:

```sh
pnpm check
pnpm build
pnpm preview
```

The static application is written to `dist/`. Deploy its contents to any static
web server. For a deployment below a URL prefix, set the asset base at build
time, including its trailing slash:

```sh
BOKEH_DEMO_BASE=/react/ pnpm build
```

## Embedding

The React adapter keeps one Bokeh document alive while its two roots are mounted
in separate page elements. React state drives the native sliders and animation.
The cross-section plot can be unmounted and mounted again without recreating
the shared Bokeh models.

```tsx
import {BokehDocument, BokehRoot} from "@bokeh/react"

<BokehDocument models={dashboard.models}>
  <section><BokehRoot model={dashboard.field}/></section>
  <aside><BokehRoot model={dashboard.profile}/></aside>
</BokehDocument>
```

- `src/App.tsx`: React state, native controls, animation, and adapter components.
- `src/main.tsx`: React entry point.
- `src/waves.ts`: Bokeh models and interference calculations.
- `src/core.ts`: shared plot styling within this application.
- `index.html`: page layout, navigation, source link, and short embed example.
- `public/assets/`: the included site styles and icon.

BokehJS and its adapter are pinned to the same `4.0.0-dev.5` release. The included
pnpm configuration permits those development packages and the esbuild install
script. No Python server is required. The site navigation and external brand
logo retain the links used on demo.bokeh.org.
