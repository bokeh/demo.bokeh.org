const {x, y} = cb_obj
const {left, right, bottom, top} = box
const tolerance = 0.025
const within_x = left - tolerance <= x && x <= right + tolerance
const within_y = bottom - tolerance <= y && y <= top + tolerance
const near_left = within_y && Math.abs(x - left) <= tolerance
const near_right = within_y && Math.abs(x - right) <= tolerance
const near_bottom = within_x && Math.abs(y - bottom) <= tolerance
const near_top = within_x && Math.abs(y - top) <= tolerance

let mode = ""
if (near_left && near_bottom) mode = "bottom_left"
else if (near_right && near_bottom) mode = "bottom_right"
else if (near_right && near_top) mode = "top_right"
else if (near_left && near_top) mode = "top_left"
else if (left <= x && x <= right && bottom <= y && y <= top) mode = "move"

state.data = {
  mode: [mode],
  start_x: [x],
  start_y: [y],
  left: [left],
  right: [right],
  bottom: [bottom],
  top: [top],
}
state.change.emit()
