"use client"

import {useEffect, useState} from "react"
import {BokehDocument, BokehRoot} from "@bokeh/react"
import {createInterference} from "../src/waves"

type Parameters = {frequency: number, separation: number, phase: number, sliceY: number}

export default function WaveLab({initial}: {initial: Parameters}) {
  const [dashboard] = useState(createInterference)
  const [frequency, setFrequency] = useState(initial.frequency)
  const [separation, setSeparation] = useState(initial.separation)
  const [phase, setPhase] = useState(initial.phase)
  const [sliceY, setSliceY] = useState(initial.sliceY)
  const [playing, setPlaying] = useState(false)
  const [showProfile, setShowProfile] = useState(true)
  const [reducedMotion, setReducedMotion] = useState(false)
  const [stats, setStats] = useState({peak: 0, energy: 0})

  useEffect(() => {
    setStats(dashboard.update(frequency, separation, phase, sliceY))
  }, [dashboard, frequency, separation, phase, sliceY])

  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)")
    const changed = () => {setReducedMotion(preference.matches); if (preference.matches) setPlaying(false)}
    changed()
    preference.addEventListener("change", changed)
    return () => preference.removeEventListener("change", changed)
  }, [])

  useEffect(() => {
    if (!playing || reducedMotion) return
    let frame = 0, last = 0
    const animate = (now: number) => {
      if (last === 0) last = now
      if (now - last >= 70) {
        const elapsed = Math.min(now - last, 150)
        setPhase((value) => (value + elapsed*.0015)%(2*Math.PI))
        last = now
      }
      frame = requestAnimationFrame(animate)
    }
    frame = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frame)
  }, [playing, reducedMotion])

  return <div className="demo-workbench">
    <div className="demo-controls">
      <label className="control" htmlFor="wave-frequency"><span>Frequency <output>{frequency.toFixed(1)}</output></span><input id="wave-frequency" type="range" min="0.8" max="4.8" step="0.1" value={frequency} onChange={(event) => setFrequency(event.target.valueAsNumber)}/></label>
      <label className="control" htmlFor="emitter-separation"><span>Source separation <output>{separation.toFixed(1)}</output></span><input id="emitter-separation" type="range" min="0.6" max="6" step="0.1" value={separation} onChange={(event) => setSeparation(event.target.valueAsNumber)}/></label>
      <label className="control" htmlFor="wave-phase"><span>Phase <output>{(phase/Math.PI).toFixed(2)}π</output></span><input id="wave-phase" type="range" min="0" max={2*Math.PI} step="0.02" value={phase} onChange={(event) => setPhase(event.target.valueAsNumber)}/></label>
      <button className="demo-button" type="button" disabled={reducedMotion} aria-pressed={playing} onClick={() => setPlaying(!playing)}>{playing ? "Pause waves" : "Play waves"}</button>
    </div>
    {reducedMotion && <p className="note motion-note">Reduced motion is enabled. Move the phase slider to explore the waves one frame at a time.</p>}
    <div className="stats-strip">
      <div className="stat"><span>Wavelength</span><strong>{(Math.PI/frequency).toFixed(2)} <small>units</small></strong></div>
      <div className="stat"><span>Slice peak</span><strong>{stats.peak.toFixed(2)}</strong></div>
      <div className="stat"><span>Mean square amplitude</span><strong>{stats.energy.toFixed(3)}</strong></div>
    </div>
    <BokehDocument models={dashboard.models}>
      <div className="workspace-grid wave-grid">
        <section className="plot-card wave-field">
          <div className="card-heading"><div><p className="eyebrow">01 / The wave field</p><h2>When two ripples meet</h2></div><span className="wave-status"><span className={playing ? "running" : ""}/>{playing ? "In motion" : "Paused"}</span></div>
          <BokehRoot model={dashboard.field} className="plot-host"/>
          <div className="wave-scale"><span>Trough</span><span className="wave-gradient"/><span>Crest</span></div>
          <p className="note">Two white dots mark the sources. Light bands reveal cancellation; deep colors reveal reinforcement.</p>
        </section>
        <div className="wave-side">
          <aside className="wave-story"><p className="eyebrow">A small interference lab</p><h2>More than the sum</h2><p>Change the distance between the sources to reshape the pattern. The gold line cuts across the field; below, the two individual waves combine into one.</p>
            <label className="control" htmlFor="wave-slice"><span>Cross section height <output>{sliceY.toFixed(1)}</output></span><input id="wave-slice" type="range" min="-4.5" max="4.5" step="0.1" value={sliceY} onChange={(event) => setSliceY(event.target.valueAsNumber)}/></label>
            <label className="profile-toggle"><input id="show-profile" type="checkbox" checked={showProfile} onChange={(event) => setShowProfile(event.target.checked)}/> Show cross section</label>
          </aside>
          {showProfile ? <section className="plot-card"><div className="card-heading"><div><p className="eyebrow">02 / The cross section</p><h2>Wave amplitudes</h2></div></div><BokehRoot model={dashboard.profile} className="plot-host"/><div className="wave-key"><span className="key-line source-a"/> Source A <span className="key-line source-b"/> Source B <span className="key-line combined"/> Combined</div></section>
            : <div className="profile-placeholder"><p className="eyebrow">Cross section hidden</p><p>The wave field keeps running. Show the cross section again to attach its Bokeh root back into the page.</p></div>}
        </div>
      </div>
    </BokehDocument>
  </div>
}
