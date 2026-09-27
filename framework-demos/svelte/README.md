# Svelte + Bokeh: Where waves meet

A standalone Svelte app with two Bokeh plots and native HTML controls.

Svelte runes drive the controls and readouts. The `bokehDocument` action shares the Bokeh document, and separate `bokehRoot` actions mount its plots in the page layout. Hiding the cross section destroys its view; showing it again mounts the same model.

## Run locally

Copy this directory on its own. It includes the plotting code, page, styles,
configuration, and dependency lockfile; no files from the parent repository are
needed. Install Node.js 24 or later and pnpm 11.25.0, then run in this directory:

```sh
pnpm install --frozen-lockfile
pnpm dev
```

Open the local URL printed by Vite.

## Check and build

```sh
pnpm check
pnpm build
pnpm preview
```

The production build is written to `dist/`. Serve that directory with any
static web server. No Python or Bokeh server is required.

For deployment below a URL prefix, set `BOKEH_DEMO_BASE` when building:

```sh
BOKEH_DEMO_BASE=/examples/svelte/ pnpm build
```

The page and `public/assets/` contain a snapshot of the Bokeh demo site's
header, footer, and styles. The demo site uses the same app with its own asset
prefix; the app has no build-time dependency on that site.

## Source

- `src/App.svelte` mounts the Bokeh views and implements the Svelte controls.
- `src/waves.ts` builds and updates the interference field and cross section.
- `src/core.ts` defines the plot styling.
- `index.html` contains the page shell, source link, and short adapter example.

The npm Bokeh packages are pinned to `4.0.0-dev.5`. Update the BokehJS and
adapter versions together when moving to a newer release.
