# Web Components + Bokeh: Where waves meet

A complete TypeScript application with Bokeh custom elements, native HTML
controls, and a wave interference simulation. Copy this directory anywhere and
run it on its own; it does not import files from the demo site or another example.

## Run

Install Node.js 24 or newer (which includes npm), then run from this directory:

```sh
npm ci
npm run dev
```

Open the local URL printed by Vite, normally <http://127.0.0.1:5173>. To check,
build, and preview the production files:

```sh
npm run check
npm run build
npm run preview
```

The preview is served at <http://127.0.0.1:4173>. To use another port, run
`npm run preview -- --port 4180`.

The static application is written to `dist/`. Deploy its contents to any static
web server. For a deployment below a URL prefix, set the asset base at build
time, including its trailing slash:

```sh
BOKEH_DEMO_BASE=/components/ npm run build
```

## Embedding

`<bokeh-document>` owns the shared Bokeh models. One `<bokeh-root>` is nested
inside it; the other lives elsewhere in the page and refers to the document
explicitly. The native `<wave-controls>` element sends custom events to update
the models. The cross-section root can be detached and reattached while the
document remains mounted.

```ts
import {defineBokehDocumentElement, defineBokehRootElement}
  from "@bokeh/web-component"

defineBokehDocumentElement()
defineBokehRootElement()

provider.models = dashboard.models
fieldRoot.model = dashboard.field
profileRoot.bokehDocument = provider
profileRoot.model = dashboard.profile
```

```html
<bokeh-document id="plots">
  <bokeh-root id="field"></bokeh-root>
</bokeh-document>
<aside><bokeh-root id="profile"></bokeh-root></aside>
```

- `src/main.ts`: custom elements, native controls, animation, and adapter setup.
- `src/waves.ts`: Bokeh models and interference calculations.
- `src/core.ts`: shared plot styling within this application.
- `index.html`: page layout, navigation, source link, and short embed example.
- `public/assets/`: the included site styles and icon.

BokehJS and its adapter are pinned to the same `4.0.0-dev.5` release. The included
`package-lock.json` lets `npm ci` reproduce the dependency versions. No Python
server or UI framework is required. The site navigation and external brand logo
retain the links used on demo.bokeh.org.
