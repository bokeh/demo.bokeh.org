import {Plotting} from "@bokeh/bokehjs"

export const colors = {
  coral: "#d95b43", teal: "#4f7b7c", gold: "#ecd078", violet: "#7c4b78",
  plum: "#2a1723", paper: "#fffdf9", ink: "#211f20",
}

export function makePlot(options: Parameters<typeof Plotting.figure>[0] = {}) {
  const plot = Plotting.figure({
    height: 380, sizing_mode: "stretch_width", tools: "pan,wheel_zoom,box_zoom,reset,save",
    toolbar_location: "above", background_fill_color: colors.paper,
    border_fill_color: colors.paper, outline_line_color: "#ddd5cc",
    min_border_left: 48, min_border_right: 15,
    ...options,
  })
  plot.toolbar.logo = null
  for (const axis of plot.axis) {
    axis.axis_line_color = "#c4b8ae"
    axis.major_tick_line_color = "#c4b8ae"
    axis.minor_tick_line_color = null
    axis.major_label_text_color = "#645961"
    axis.axis_label_text_color = "#645961"
    axis.axis_label_text_font_style = "normal"
    axis.major_label_text_font_size = "11px"
  }
  for (const grid of plot.grid) {
    grid.grid_line_color = "#ede6dd"
  }
  return plot
}
