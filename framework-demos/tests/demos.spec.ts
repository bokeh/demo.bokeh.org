import {test, expect} from "@playwright/test"
import type {Locator, Page} from "@playwright/test"

async function painted(canvas: Locator) {
  await expect(canvas).toBeVisible()
  // A mounted toolbar alone is insufficient: wait for a real rendered plot.
  await expect.poll(() => canvas.evaluate((element: HTMLCanvasElement) => {
    const context = element.getContext("2d")!
    const pixels = context.getImageData(0, 0, element.width, element.height).data
    const colors = new Set<number>()
    for (let i = 0; i < pixels.length; i += 116) {
      if (pixels[i + 3] > 0) colors.add((pixels[i] << 16) + (pixels[i + 1] << 8) + pixels[i + 2])
    }
    return colors.size
  })).toBeGreaterThan(20)
}

async function fingerprint(canvas: Locator) {
  return canvas.evaluate((element: HTMLCanvasElement) => element.toDataURL())
}

async function slider(page: Page, id: string, value: string) {
  await page.locator(id).fill(value)
}

test.beforeEach(async ({page}) => {
  // The production logo is the only external page asset; tests need no network.
  await page.route("https://static.bokeh.org/**", (route) => route.fulfill({contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="108" height="32"><text y="24">bokeh</text></svg>'}))
})

for (const route of ["react", "vue", "svelte", "components", "nextjs"]) {
  test(`${route}: two independent roots, tools, isolated assets and mobile layout`, async ({page}) => {
    const errors: string[] = [], sockets: string[] = [], requests: string[] = []
    page.on("pageerror", (error) => errors.push(error.message))
    page.on("websocket", (socket) => sockets.push(socket.url()))
    page.on("request", (request) => requests.push(request.url()))
    await page.goto(`/${route}`)
    await expect(page.getByRole("heading", {level: 1})).toBeVisible()
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/)
    await expect(page.locator(".site-header .brand")).toHaveAttribute("href", "/")
    await expect(page.getByRole("link", {name: "View full app source"})).toHaveAttribute("href", new RegExp(`/framework-demos/${route === "nextjs" ? "next" : `src/${route}`}$`))
    await expect(page.locator(".embed-example code")).toContainText(route === "components" ? "bokeh-root" : route === "svelte" ? "bokehRoot" : "BokehRoot")
    await painted(page.locator("canvas").first())
    await painted(page.locator(".plot-host").nth(1).locator("canvas").first())
    await expect(page.locator(".bk-Toolbar").first()).toBeVisible()
    await page.setViewportSize({width: 390, height: 844})
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await painted(page.locator("canvas").first())
    expect(errors).toEqual([])
    expect(sockets).toEqual([])
    expect(requests.filter((url) => /bokeh.*3\.10|cdn\.bokeh|\/autoload|\/ws(?:\?|$)/.test(url))).toEqual([])
  })
}

for (const route of ["react", "vue", "svelte", "components", "nextjs"]) {
  test(`${route}: native controls, animation and independent profile lifecycle`, async ({page}) => {
    const errors: string[] = []
    page.on("pageerror", (error) => errors.push(error.message))
    await page.goto(`/${route}`)
    await expect(page.getByRole("heading", {level: 1})).toHaveText("Where waves meet")
    const field = page.locator("canvas").first()
    await painted(field)
    const before = await fingerprint(field)
    await slider(page, "#wave-frequency", "4.2")
    await expect.poll(() => fingerprint(field)).not.toEqual(before)
    const changed = await fingerprint(field)
    await slider(page, "#emitter-separation", "4")
    await expect.poll(() => fingerprint(field)).not.toEqual(changed)
    await page.getByLabel("Show cross section").uncheck()
    await expect(page.locator(".plot-host")).toHaveCount(1)
    await slider(page, "#wave-phase", "2.4")
    await slider(page, "#wave-slice", "-2")
    await page.getByLabel("Show cross section").check()
    await painted(page.locator(".plot-host").nth(1).locator("canvas").first())
    const paused = await fingerprint(field)
    await page.getByRole("button", {name: "Play waves"}).click()
    await expect.poll(() => fingerprint(field)).not.toEqual(paused)
    await page.getByRole("button", {name: "Pause waves"}).click()
    await page.emulateMedia({reducedMotion: "reduce"})
    await expect(page.getByRole("button", {name: "Play waves"})).toBeDisabled()
    expect(errors).toEqual([])
  })
}

test("Vue Teleport keeps wave notes live and restores keyboard focus", async ({page}) => {
  await page.goto("/vue")
  await painted(page.locator("canvas").first())
  await page.getByRole("button", {name: "Wave notes"}).click()
  await expect(page.locator("body > #wave-inspector")).toBeVisible()
  await slider(page, "#wave-frequency", "3.5")
  await expect(page.locator("#wave-inspector")).toContainText("0.90 units")
  await page.keyboard.press("Escape")
  await expect(page.locator("#wave-inspector")).toHaveCount(0)
  await expect(page.getByRole("button", {name: "Wave notes"})).toBeFocused()
})

test("Next.js exports its page and initial controls as static HTML", async ({request}) => {
  const response = await request.get("/nextjs")
  const html = await response.text()
  expect(html).toContain("Where waves meet")
  expect(html).toContain('id="wave-frequency"')
  expect(html).toContain("Embed Bokeh in Next.js")
  expect(html).toContain("/assets/frameworks/nextjs/_next/")
})
