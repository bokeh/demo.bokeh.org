<script setup lang="ts">
import {computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch} from "vue"
import {BokehDocument, BokehRoot} from "@bokeh/vue"

import {createInterference} from "../shared/waves"

const dashboard = markRaw(createInterference())
const frequency = ref(2.4)
const separation = ref(2.6)
const phase = ref(0.7)
const sliceY = ref(1.5)
const playing = ref(false)
const showProfile = ref(true)
const reducedMotion = ref(false)
const stats = ref({peak: 0, energy: 0})
const wavelength = computed(() => Math.PI/frequency.value)
watch([frequency, separation, phase, sliceY], () => {
  stats.value = dashboard.update(frequency.value, separation.value, phase.value, sliceY.value)
}, {immediate: true})

let preference: MediaQueryList | null = null
const applyPreference = () => {
  reducedMotion.value = preference?.matches ?? false
  if (reducedMotion.value) playing.value = false
}
onMounted(() => {
  preference = window.matchMedia("(prefers-reduced-motion: reduce)")
  applyPreference()
  preference.addEventListener("change", applyPreference)
})
watch([playing, reducedMotion], ([running, reduce], _previous, onCleanup) => {
  if (!running || reduce) return
  let frame = 0
  let last = 0
  const animate = (now: number) => {
    if (last == 0) last = now
    if (now - last >= 70) {
      phase.value = (phase.value + Math.min(now - last, 150)*0.0015)%(2*Math.PI)
      last = now
    }
    frame = requestAnimationFrame(animate)
  }
  frame = requestAnimationFrame(animate)
  onCleanup(() => cancelAnimationFrame(frame))
})

const inspectorOpen = ref(false)
const inspectorTrigger = ref<HTMLButtonElement | null>(null)
const inspectorClose = ref<HTMLButtonElement | null>(null)
const closeOnEscape = (event: KeyboardEvent) => {
  if (event.key == "Escape") inspectorOpen.value = false
}
watch(inspectorOpen, async (open) => {
  if (open) window.addEventListener("keydown", closeOnEscape)
  else window.removeEventListener("keydown", closeOnEscape)
  await nextTick()
  if (inspectorOpen.value == open) {
    if (open) inspectorClose.value?.focus()
    else inspectorTrigger.value?.focus()
  }
})
onBeforeUnmount(() => {
  preference?.removeEventListener("change", applyPreference)
  window.removeEventListener("keydown", closeOnEscape)
})
</script>

<template>
  <div class="demo-workbench">
    <div class="demo-controls">
      <label class="control" for="wave-frequency">
        <span>Frequency <output>{{ frequency.toFixed(1) }}</output></span>
        <input id="wave-frequency" v-model.number="frequency" type="range" min="0.8" max="4.8" step="0.1">
      </label>
      <label class="control" for="emitter-separation">
        <span>Source separation <output>{{ separation.toFixed(1) }}</output></span>
        <input id="emitter-separation" v-model.number="separation" type="range" min="0.6" max="6" step="0.1">
      </label>
      <label class="control" for="wave-phase">
        <span>Phase <output>{{ (phase/Math.PI).toFixed(2) }}π</output></span>
        <input id="wave-phase" v-model.number="phase" type="range" min="0" :max="2*Math.PI" step="0.02">
      </label>
      <button class="demo-button" type="button" :disabled="reducedMotion" :aria-pressed="playing" @click="playing = !playing">{{ playing ? "Pause waves" : "Play waves" }}</button>
    </div>
    <p v-if="reducedMotion" class="note motion-note">Reduced motion is enabled. Move the phase slider to explore the waves one frame at a time.</p>

    <div class="stats-strip">
      <div class="stat"><span>Wavelength</span><strong>{{ wavelength.toFixed(2) }} <small>units</small></strong></div>
      <div class="stat"><span>Slice peak</span><strong>{{ stats.peak.toFixed(2) }}</strong></div>
      <div class="stat"><span>Mean square amplitude</span><strong>{{ stats.energy.toFixed(3) }}</strong></div>
    </div>

    <BokehDocument :models="dashboard.models">
      <div class="workspace-grid wave-grid">
        <section class="plot-card wave-field">
          <div class="card-heading"><div><p class="eyebrow">01 / THE WAVE FIELD</p><h2>When two ripples meet</h2></div><span class="wave-status"><span :class="{running: playing}"></span>{{ playing ? "In motion" : "Paused" }}</span></div>
          <BokehRoot :model="dashboard.field" class="plot-host" />
          <div class="wave-scale"><span>Trough</span><span class="wave-gradient"></span><span>Crest</span></div>
          <p class="note">Two white dots mark the sources. Light bands reveal cancellation; deep colors reveal reinforcement.</p>
        </section>
        <div class="wave-side">
          <aside class="wave-story">
            <p class="eyebrow">A SMALL INTERFERENCE LAB</p>
            <h2>More than the sum</h2>
            <p>Change the distance between the sources to reshape the pattern. The gold line cuts across the field; below, the two individual waves combine into one.</p>
            <label class="control" for="wave-slice"><span>Cross section height <output>{{ sliceY.toFixed(1) }}</output></span><input id="wave-slice" v-model.number="sliceY" type="range" min="-4.5" max="4.5" step="0.1"></label>
            <label class="profile-toggle"><input id="show-profile" v-model="showProfile" type="checkbox"> Show cross section</label>
          </aside>
          <section v-if="showProfile" class="plot-card">
            <div class="card-heading"><div><p class="eyebrow">02 / THE CROSS SECTION</p><h2>Wave amplitudes</h2></div></div>
            <BokehRoot :model="dashboard.profile" class="plot-host" />
            <div class="wave-key"><span class="key-line source-a"></span> Source A <span class="key-line source-b"></span> Source B <span class="key-line combined"></span> Combined</div>
          </section>
          <div v-else class="profile-placeholder"><p class="eyebrow">CROSS SECTION HIDDEN</p><p>The wave field keeps running. Show the cross section again to attach its Bokeh root back into the page.</p></div>
        </div>
      </div>
    </BokehDocument>
    <div class="framework-note"><strong>Vue</strong><div><p>Vue’s reactive controls update two Bokeh plots in a shared document. The wave notes use Teleport.</p><button ref="inspectorTrigger" class="demo-button secondary wave-notes-button" type="button" @click="inspectorOpen = !inspectorOpen" :aria-expanded="inspectorOpen" aria-controls="wave-inspector">Wave notes</button></div></div>

    <Teleport to="body">
      <aside v-if="inspectorOpen" id="wave-inspector" class="wave-inspector" aria-label="Wave notes">
        <div class="card-heading"><p class="eyebrow">WAVE NOTES</p><button ref="inspectorClose" class="demo-button secondary" type="button" @click="inspectorOpen = false">Close</button></div>
        <h2>Where waves meet</h2>
        <p>Two synthetic circular waves add together. Matching peaks reinforce each other; opposite displacements cancel.</p>
        <p>The current wavelength is <strong>{{ wavelength.toFixed(2) }} units</strong>. The selected cross section reaches an amplitude of <strong>{{ stats.peak.toFixed(2) }}</strong>.</p>
        <p class="note">Vue teleports these live notes into the document body while preserving their reactive state.</p>
      </aside>
    </Teleport>
  </div>
</template>

<style scoped>
.wave-notes-button { margin-top: 12px; }
.wave-inspector { position: fixed; z-index: 100; right: 24px; bottom: 24px; width: min(400px, calc(100vw - 48px)); box-sizing: border-box; padding: 24px; background: #fffaf0; color: #302e30; border: 2px solid #a27c61; font-family: inherit; }
.wave-inspector h2 { font-size: 23px; margin: 16px 0; }
.wave-inspector p { line-height: 1.6; }
</style>
