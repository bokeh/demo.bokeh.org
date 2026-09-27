import {mount} from "svelte"
import App from "./App.svelte"

const target = document.getElementById("framework-app")!
target.replaceChildren()
mount(App, {target})
