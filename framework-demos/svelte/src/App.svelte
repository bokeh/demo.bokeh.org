<script lang="ts">
  import {onMount} from "svelte"
  import {bokehDocument, bokehRoot} from "@bokeh/svelte"

  import {createInterference} from "./waves"

  const dashboard = createInterference()
  let frequency = $state(2.4)
  let separation = $state(2.6)
  let phase = $state(0.7)
  let sliceY = $state(1.5)
  let playing = $state(false)
  let showProfile = $state(true)
  let reducedMotion = $state(false)
  let stats = $state({peak: 0, energy: 0})
  const wavelength = $derived(Math.PI/frequency)

  $effect(() => {
    stats = dashboard.update(frequency, separation, phase, sliceY)
  })

  onMount(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)")
    const applyPreference = () => {
      reducedMotion = preference.matches
      if (reducedMotion) playing = false
    }
    applyPreference()
    preference.addEventListener("change", applyPreference)
    return () => preference.removeEventListener("change", applyPreference)
  })

  $effect(() => {
    if (!playing || reducedMotion) return
    let frame = 0
    let last = 0
    const animate = (now: number) => {
      if (last == 0) last = now
      if (now - last >= 70) {
        phase = (phase + Math.min(now - last, 150)*0.0015)%(2*Math.PI)
        last = now
      }
      frame = requestAnimationFrame(animate)
    }
    frame = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frame)
  })
</script>

<div class="demo-workbench" use:bokehDocument={{models: dashboard.models}}>
  <div class="demo-controls">
    <label class="control" for="wave-frequency">
      <span>Frequency <output>{frequency.toFixed(1)}</output></span>
      <input id="wave-frequency" type="range" min="0.8" max="4.8" step="0.1" bind:value={frequency}>
    </label>
    <label class="control" for="emitter-separation">
      <span>Source separation <output>{separation.toFixed(1)}</output></span>
      <input id="emitter-separation" type="range" min="0.6" max="6" step="0.1" bind:value={separation}>
    </label>
    <label class="control" for="wave-phase">
      <span>Phase <output>{(phase/Math.PI).toFixed(2)}π</output></span>
      <input id="wave-phase" type="range" min="0" max={2*Math.PI} step="0.02" bind:value={phase}>
    </label>
    <button class="demo-button" type="button" disabled={reducedMotion} aria-pressed={playing} onclick={() => playing = !playing}>{playing ? "Pause waves" : "Play waves"}</button>
  </div>
  {#if reducedMotion}<p class="note motion-note">Reduced motion is enabled. Move the phase slider to explore the waves one frame at a time.</p>{/if}

  <div class="stats-strip">
    <div class="stat"><span>Wavelength</span><strong>{wavelength.toFixed(2)} <small>units</small></strong></div>
    <div class="stat"><span>Slice peak</span><strong>{stats.peak.toFixed(2)}</strong></div>
    <div class="stat"><span>Mean square amplitude</span><strong>{stats.energy.toFixed(3)}</strong></div>
  </div>

  <div class="workspace-grid wave-grid">
    <section class="plot-card wave-field">
      <div class="card-heading"><div><p class="eyebrow">01 / THE WAVE FIELD</p><h2>When two ripples meet</h2></div><span class="wave-status"><span class:running={playing}></span>{playing ? "In motion" : "Paused"}</span></div>
      <div class="plot-host" use:bokehRoot={{model: dashboard.field}}></div>
      <div class="wave-scale"><span>Trough</span><span class="wave-gradient"></span><span>Crest</span></div>
      <p class="note">Two white dots mark the sources. Light bands reveal cancellation; deep colors reveal reinforcement.</p>
    </section>
    <div class="wave-side">
      <aside class="wave-story">
        <p class="eyebrow">A SMALL INTERFERENCE LAB</p>
        <h2>More than the sum</h2>
        <p>Change the distance between the sources to reshape the pattern. The gold line cuts across the field; below, the two individual waves combine into one.</p>
        <label class="control" for="wave-slice"><span>Cross section height <output>{sliceY.toFixed(1)}</output></span><input id="wave-slice" type="range" min="-4.5" max="4.5" step="0.1" bind:value={sliceY}></label>
        <label class="profile-toggle"><input id="show-profile" type="checkbox" bind:checked={showProfile}> Show cross section</label>
      </aside>
      {#if showProfile}
        <section class="plot-card">
          <div class="card-heading"><div><p class="eyebrow">02 / THE CROSS SECTION</p><h2>Wave amplitudes</h2></div></div>
          <div class="plot-host" use:bokehRoot={{model: dashboard.profile}}></div>
          <div class="wave-key"><span class="key-line source-a"></span> Source A <span class="key-line source-b"></span> Source B <span class="key-line combined"></span> Combined</div>
        </section>
      {:else}
        <div class="profile-placeholder"><p class="eyebrow">CROSS SECTION HIDDEN</p><p>The wave field keeps running. Show the cross section again to attach its Bokeh root back into the page.</p></div>
      {/if}
    </div>
  </div>
  <div class="framework-note"><strong>Svelte</strong><p>Svelte runes drive the controls and readouts. Actions mount each Bokeh plot and remove its view when hidden.</p></div>
</div>
