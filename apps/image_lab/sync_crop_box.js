const left = cb_obj.data.left[0]
const right = cb_obj.data.right[0]
const bottom = cb_obj.data.bottom[0]
const top = cb_obj.data.top[0]

box.update({left, right, bottom, top})
handles.data = {
  x: [left, right, right, left],
  y: [bottom, bottom, top, top],
}
handles.change.emit()
