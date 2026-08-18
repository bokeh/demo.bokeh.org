const throttle = cb_obj.tags[0] ?? {last_sent: 0, timeout: null}
const send_request = () => {
  const value = cb_obj.value
  if (request.data.value[0] != value) {
    request.data = {value: [value]}
    request.change.emit()
  }
  throttle.last_sent = Date.now()
  throttle.timeout = null
}

const remaining = wait - (Date.now() - throttle.last_sent)
if (flush || remaining <= 0) {
  clearTimeout(throttle.timeout)
  send_request()
} else {
  clearTimeout(throttle.timeout)
  throttle.timeout = setTimeout(send_request, remaining)
}
cb_obj.tags = [throttle]
