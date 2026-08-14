const loader = document.querySelector(".application-loading")
if (loader != null) {
  loader.closest(".application-canvas")?.setAttribute("aria-busy", "false")
  loader.remove()
}
