import {ColumnDataSource, HoverTool, LinearColorMapper} from "@bokeh/bokehjs"
import {ndarray} from "@bokeh/bokehjs/build/js/lib/core/util/ndarray"

import {colors, makePlot} from "./core"

const width = 180
const height = 150
const extent = 6

const colorStops = ["#17375e", "#236b9a", "#3babc1", "#a4dfdf", "#fff9ed", "#f6c39f", "#ee8767", "#ca495b", "#772c50"]
// A smooth diverging ramp keeps the neutral midpoint at zero amplitude.
const wavePalette = Array.from({length: 257}, (_, index) => {
  const position = index/256*(colorStops.length - 1)
  const left = Math.min(Math.floor(position), colorStops.length - 2)
  const fraction = position - left
  const channels = [1, 3, 5].map((offset) => {
    const a = parseInt(colorStops[left].slice(offset, offset + 2), 16)
    const b = parseInt(colorStops[left + 1].slice(offset, offset + 2), 16)
    return Math.round(a + (b - a)*fraction).toString(16).padStart(2, "0")
  })
  return `#${channels.join("")}`
})

function signal(x: number, y: number, origin: number, frequency: number, phase: number) {
  const distance = Math.hypot(x - origin, y)
  return Math.sin(frequency*distance*2 - phase)/Math.sqrt(1 + 0.6*distance)
}

export function createInterference() {
  const raster = ColumnDataSource.create({data: {image: []}})
  const emitterData = ColumnDataSource.create({data: {x: [-1.3, 1.3], y: [0, 0]}})
  const slice = ColumnDataSource.create({data: {x: [-extent, extent], y: [1.5, 1.5]}})
  const profileData = ColumnDataSource.create({data: {x: [], a: [], b: [], sum: [], zero: []}})
  const mapper = LinearColorMapper.create({
    palette: wavePalette,
    low: -1.65,
    high: 1.65,
  })
  const field = makePlot({
    height: 440, x_range: [-extent, extent], y_range: [-5, 5],
    x_axis_label: "Horizontal distance", y_axis_label: "Vertical distance",
    match_aspect: true,
  })
  field.image({image: {field: "image"}, source: raster, x: -extent, y: -5, dw: extent*2, dh: 10, color_mapper: mapper})
  field.line({field: "x"}, {field: "y"}, {source: slice, line_color: colors.paper, line_width: 4, line_alpha: 0.8})
  field.line({field: "x"}, {field: "y"}, {source: slice, line_color: colors.gold, line_width: 2, line_dash: "dashed"})
  field.scatter({field: "x"}, {field: "y"}, {source: emitterData, size: 16, fill_color: colors.paper, line_color: colors.ink, line_width: 2, marker: "circle"})
  field.scatter({field: "x"}, {field: "y"}, {source: emitterData, size: 4, fill_color: colors.ink, line_color: colors.ink})

  const profile = makePlot({
    height: 270, x_range: field.x_range, y_range: [-2.1, 2.1],
    x_axis_label: "Horizontal distance", y_axis_label: "Amplitude",
  })
  profile.varea({field: "x"}, {field: "zero"}, {field: "sum"}, {source: profileData, fill_color: colors.violet, fill_alpha: 0.13})
  profile.line({field: "x"}, {field: "a"}, {source: profileData, line_color: colors.coral, line_width: 1.5, line_alpha: 0.7, line_dash: "dashed"})
  profile.line({field: "x"}, {field: "b"}, {source: profileData, line_color: colors.teal, line_width: 1.5, line_alpha: 0.7, line_dash: "dashed"})
  const combined = profile.line({field: "x"}, {field: "sum"}, {source: profileData, line_color: colors.plum, line_width: 3})
  profile.add_tools(HoverTool.create({renderers: [combined], mode: "vline", tooltips: [["Position", "@x{0.00}"], ["Combined wave", "@sum{0.000}"]]}))

  function update(frequency: number, separation: number, phase: number, sliceY: number) {
    const values = new Float64Array(width*height)
    for (let row = 0; row < height; row++) {
      const y = -5 + 10*row/(height - 1)
      for (let col = 0; col < width; col++) {
        const x = -extent + extent*2*col/(width - 1)
        values[row*width + col] = signal(x, y, -separation/2, frequency, phase) + signal(x, y, separation/2, frequency, phase)
      }
    }
    raster.data = {image: [ndarray(values, {dtype: "float64", shape: [height, width]})]}
    emitterData.data = {x: [-separation/2, separation/2], y: [0, 0]}
    slice.data = {x: [-extent, extent], y: [sliceY, sliceY]}
    const x = Array.from({length: 240}, (_, index) => -extent + extent*2*index/239)
    const a = x.map((position) => signal(position, sliceY, -separation/2, frequency, phase))
    const b = x.map((position) => signal(position, sliceY, separation/2, frequency, phase))
    const sum = a.map((value, index) => value + b[index])
    profileData.data = {x, a, b, sum, zero: x.map(() => 0)}
    return {
      peak: Math.max(...sum.map(Math.abs)),
      energy: sum.reduce((total, value) => total + value*value, 0)/sum.length,
    }
  }

  return {field, profile, models: [field, profile], update}
}
