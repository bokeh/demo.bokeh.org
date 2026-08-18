request.data = {
  left: [box.left],
  right: [box.right],
  bottom: [box.bottom],
  top: [box.top],
}
request.change.emit()
state.tags = [Date.now()]
state.data.mode[0] = ""
state.change.emit()
