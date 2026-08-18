const mode = state.data.mode[0]
if (mode === "") return

const dx = cb_obj.x - state.data.start_x[0]
const dy = cb_obj.y - state.data.start_y[0]
const original = {
  left: state.data.left[0],
  right: state.data.right[0],
  bottom: state.data.bottom[0],
  top: state.data.top[0],
}
const min_size = 0.035
let {left, right, bottom, top} = original

if (mode === "move") {
  const width = right - left
  const height = top - bottom
  left = Math.max(0, Math.min(1 - width, left + dx))
  bottom = Math.max(0, Math.min(1 - height, bottom + dy))
  right = left + width
  top = bottom + height
} else {
  if (mode.includes("left")) left = Math.max(0, Math.min(right - min_size, left + dx))
  if (mode.includes("right")) right = Math.min(1, Math.max(left + min_size, right + dx))
  if (mode.includes("bottom")) bottom = Math.max(0, Math.min(top - min_size, bottom + dy))
  if (mode.includes("top")) top = Math.min(1, Math.max(bottom + min_size, top + dy))
}

box.update({left, right, bottom, top})
handles.data = {
  x: [left, right, right, left],
  y: [bottom, bottom, top, top],
}
handles.change.emit()
