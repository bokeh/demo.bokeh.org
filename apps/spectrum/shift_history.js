const image = history.data.image[0]
const latest = cb_obj.data.image[0]
const width = image.shape[1]
if (cb_obj.data.advance?.[0] ?? true) image.copyWithin(0, width)
image.set(latest, image.length - width)
history.change.emit()
