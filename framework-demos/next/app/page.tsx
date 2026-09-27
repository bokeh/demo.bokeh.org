import chrome from "./chrome.json"
import WaveLab from "./WaveLab"

// The server component supplies serializable parameters at static export time.
const initial = {frequency: 2.4, separation: 2.6, phase: 0.7, sliceY: 1.5}

export default function Page() {
  return <main className="application-page framework-page" id="main-content">
    <div dangerouslySetInnerHTML={{__html: chrome.intro}}/>
    <WaveLab initial={initial}/>
    <noscript><p>Enable JavaScript to explore the wave field and cross section.</p></noscript>
    <div className="framework-note"><strong>Next.js App Router</strong><p>The page and initial parameters are rendered at build time. A client component creates the shared Bokeh document and hydrates the controls. This static export needs no Node.js server.</p></div>
    <div dangerouslySetInnerHTML={{__html: chrome.embedExample}}/>
    <p className="session-note">Synthetic two-source wave model. All interactions run in your browser.</p>
  </main>
}
