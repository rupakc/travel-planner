// Social telemetry: fire and forget, props are enums or bools only (never a
// handle, id or text). A failing SDK is ignored.
export function track(event, props) {
  import('../../telemetry/client').then((m) => m.emit(event, props)).catch(() => {})
}
