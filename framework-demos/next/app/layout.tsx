import type {Metadata} from "next"
import type {ReactNode} from "react"
import chrome from "../../work/chrome.json"

export const metadata: Metadata = {
  title: "Where waves meet · Next.js · Bokeh demos",
  description: "Explore a two-source interference field and linked wave profile, built with the Next.js App Router.",
  robots: {index: false, follow: false},
}

export default function Layout({children}: {children: ReactNode}) {
  return <html lang="en"><head>
    <link rel="icon" href="/assets/bokeh-icon.svg?v=2" type="image/svg+xml"/>
    <link rel="stylesheet" href="/assets/site.css?v=14"/>
    <link rel="stylesheet" href="/assets/frameworks/frameworks.css"/>
  </head><body>
    <div style={{display: "contents"}} dangerouslySetInnerHTML={{__html: chrome.header}}/>
    {children}
    <div dangerouslySetInnerHTML={{__html: chrome.footer}}/>
  </body></html>
}
