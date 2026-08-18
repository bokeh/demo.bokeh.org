const image = history.data.image[0]
const latest = cb_obj.data.image[0]
const width = image.shape[1]
image.copyWithin(0, width)
image.set(latest, image.length - width)
history.change.emit()
