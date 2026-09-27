import {defineBokehDocumentElement, defineBokehRootElement} from "@bokeh/web-component"
import type {BokehDocumentElement, BokehRootElement} from "@bokeh/web-component"
import {createInterference} from "./waves"

defineBokehDocumentElement()
defineBokehRootElement()

type WaveSettings = {frequency: number, separation: number, phase: number}

class WaveControls extends HTMLElement {
  connectedCallback() {
    if (this.childElementCount > 0) return
    this.innerHTML = `<div class="demo-controls">
      <label class="control" for="wave-frequency"><span>Frequency <output data-frequency>2.4</output></span><input id="wave-frequency" type="range" min="0.8" max="4.8" step="0.1" value="2.4"></label>
      <label class="control" for="emitter-separation"><span>Source separation <output data-separation>2.6</output></span><input id="emitter-separation" type="range" min="0.6" max="6" step="0.1" value="2.6"></label>
      <label class="control" for="wave-phase"><span>Phase <output data-phase>0.22π</output></span><input id="wave-phase" type="range" min="0" max="${2*Math.PI}" step="0.02" value="0.7"></label>
      <button class="demo-button" type="button" aria-pressed="false">Play waves</button>
    </div>`
    this.addEventListener("input", () => this.dispatchEvent(new CustomEvent<WaveSettings>("wave-change", {detail: this.settings, bubbles: true})))
    this.querySelector("button")!.addEventListener("click", () => this.dispatchEvent(new CustomEvent("wave-play", {bubbles: true})))
  }

  get settings(): WaveSettings {
    return {
      frequency: this.querySelector<HTMLInputElement>("#wave-frequency")!.valueAsNumber,
      separation: this.querySelector<HTMLInputElement>("#emitter-separation")!.valueAsNumber,
      phase: this.querySelector<HTMLInputElement>("#wave-phase")!.valueAsNumber,
    }
  }

  set settings(settings: WaveSettings) {
    this.querySelector<HTMLInputElement>("#wave-phase")!.value = String(settings.phase)
    this.querySelector<HTMLOutputElement>("[data-frequency]")!.value = settings.frequency.toFixed(1)
    this.querySelector<HTMLOutputElement>("[data-separation]")!.value = settings.separation.toFixed(1)
    this.querySelector<HTMLOutputElement>("[data-phase]")!.value = `${(settings.phase/Math.PI).toFixed(2)}π`
  }
}
customElements.define("wave-controls", WaveControls)

const dashboard = createInterference()
const app = document.getElementById("framework-app")!
app.innerHTML = `<div class="demo-workbench">
  <wave-controls></wave-controls>
  <p class="note motion-note" hidden>Reduced motion is enabled. Move the phase slider to explore the waves one frame at a time.</p>
  <div class="stats-strip">
    <div class="stat"><span>Wavelength</span><strong><span data-wavelength>1.31</span> <small>units</small></strong></div>
    <div class="stat"><span>Slice peak</span><strong data-peak>0.00</strong></div>
    <div class="stat"><span>Mean square amplitude</span><strong data-energy>0.000</strong></div>
  </div>
  <div class="workspace-grid wave-grid">
    <bokeh-document id="wave-document">
      <section class="plot-card wave-field">
        <div class="card-heading"><div><p class="eyebrow">01 / THE WAVE FIELD</p><h2>When two ripples meet</h2></div><span class="wave-status"><span></span><output data-playing>Paused</output></span></div>
        <bokeh-root id="wave-field" class="plot-host" data-testid="wave-field"></bokeh-root>
        <div class="wave-scale"><span>Trough</span><span class="wave-gradient"></span><span>Crest</span></div>
        <p class="note">Two white dots mark the sources. Light bands reveal cancellation; deep colors reveal reinforcement.</p>
      </section>
    </bokeh-document>
    <div class="wave-side">
      <aside class="wave-story">
        <p class="eyebrow">A SMALL INTERFERENCE LAB</p>
        <h2>More than the sum</h2>
        <p>Change the distance between the sources to reshape the pattern. The gold line cuts across the field; below, the two individual waves combine into one.</p>
        <label class="control" for="wave-slice"><span>Cross section height <output data-slice>1.5</output></span><input id="wave-slice" type="range" min="-4.5" max="4.5" step="0.1" value="1.5"></label>
        <label class="profile-toggle"><input id="show-profile" type="checkbox" checked> Show cross section</label>
      </aside>
      <div id="wave-profile-slot">
        <section class="plot-card" id="wave-profile-card">
          <div class="card-heading"><div><p class="eyebrow">02 / THE CROSS SECTION</p><h2>Wave amplitudes</h2></div></div>
          <bokeh-root id="wave-profile" class="plot-host" data-testid="wave-profile"></bokeh-root>
          <div class="wave-key"><span class="key-line source-a"></span> Source A <span class="key-line source-b"></span> Source B <span class="key-line combined"></span> Combined</div>
        </section>
      </div>
    </div>
  </div>
  <p class="framework-error" role="alert" hidden></p>
  <div class="framework-note"><strong>Web Components in the details</strong><p>A synthetic two-source wave model. Native custom elements and DOM events drive the controls. The cross-section root lives outside its document element and connects through an explicit provider; hiding it preserves the shared document and wave field.</p></div>
</div>`

const provider = document.getElementById("wave-document") as BokehDocumentElement
const fieldRoot = document.getElementById("wave-field") as BokehRootElement
const profileRoot = document.getElementById("wave-profile") as BokehRootElement
const controls = app.querySelector("wave-controls") as WaveControls
const playButton = controls.querySelector("button")!
const profileSlot = document.getElementById("wave-profile-slot")!
const profileCard = document.getElementById("wave-profile-card")!
const placeholder = document.createElement("div")
placeholder.className = "profile-placeholder"
placeholder.innerHTML = `<p class="eyebrow">CROSS SECTION HIDDEN</p><p>The wave field keeps running. Show the cross section again to attach its Bokeh root back into the page.</p>`

let settings: WaveSettings = {frequency: 2.4, separation: 2.6, phase: 0.7}
let sliceY = 1.5
let playing = false
let reducedMotion = false
let frame = 0
let last = 0
let mountEvents = 0

provider.addEventListener("bokeh-mount", () => {app.dataset.mountEvents = String(++mountEvents)})
provider.addEventListener("bokeh-mount-error", (event) => {
  const error = app.querySelector<HTMLElement>(".framework-error")!
  error.textContent = `Unable to display the plots: ${String((event as CustomEvent).detail)}`
  error.hidden = false
})
provider.models = dashboard.models
fieldRoot.model = dashboard.field
// The cross section sits outside the provider's DOM subtree.
profileRoot.bokehDocument = provider
profileRoot.model = dashboard.profile

function update() {
  const stats = dashboard.update(settings.frequency, settings.separation, settings.phase, sliceY)
  controls.settings = settings
  app.querySelector("[data-wavelength]")!.textContent = (Math.PI/settings.frequency).toFixed(2)
  app.querySelector("[data-peak]")!.textContent = stats.peak.toFixed(2)
  app.querySelector("[data-energy]")!.textContent = stats.energy.toFixed(3)
  app.querySelector<HTMLOutputElement>("[data-slice]")!.value = sliceY.toFixed(1)
}

function animate(now: number) {
  if (!playing || reducedMotion) return
  if (last == 0) last = now
  if (now - last >= 70) {
    settings.phase = (settings.phase + Math.min(now - last, 150)*0.0015)%(2*Math.PI)
    last = now
    update()
  }
  frame = requestAnimationFrame(animate)
}

function setPlaying(value: boolean) {
  playing = value && !reducedMotion
  cancelAnimationFrame(frame)
  last = 0
  playButton.textContent = playing ? "Pause waves" : "Play waves"
  playButton.setAttribute("aria-pressed", String(playing))
  app.querySelector(".wave-status > span:first-child")!.classList.toggle("running", playing)
  app.querySelector("[data-playing]")!.textContent = playing ? "In motion" : "Paused"
  if (playing) frame = requestAnimationFrame(animate)
}

app.addEventListener("wave-change", (event) => {settings = (event as CustomEvent<WaveSettings>).detail; update()})
app.addEventListener("wave-play", () => setPlaying(!playing))
app.querySelector<HTMLInputElement>("#wave-slice")!.addEventListener("input", (event) => {sliceY = (event.target as HTMLInputElement).valueAsNumber; update()})
app.querySelector<HTMLInputElement>("#show-profile")!.addEventListener("change", (event) => {
  profileSlot.replaceChildren((event.target as HTMLInputElement).checked ? profileCard : placeholder)
})

const preference = window.matchMedia("(prefers-reduced-motion: reduce)")
function applyPreference() {
  reducedMotion = preference.matches
  playButton.disabled = reducedMotion
  app.querySelector<HTMLElement>(".motion-note")!.hidden = !reducedMotion
  if (reducedMotion) setPlaying(false)
}
preference.addEventListener("change", applyPreference)
window.addEventListener("pagehide", () => setPlaying(false))
applyPreference()
update()
