// Price-watch dialog: the kind-specific part of the body (the shell, alert
// mode, email and no-live-price suggestions are shared: ../PriceWatchDialog).
// Add a kind by creating its body in this folder and one line below, e.g.
//   import HotelDialogBody from './HotelDialogBody'   →   hotel: HotelDialogBody,
// Bodies get { kind, spec, preview, watch, unitLabel } (see GenericPriceBody).
import GenericPriceBody from './GenericPriceBody'

export const DIALOG_BODIES = {
}

export function dialogBodyFor(kind) {
  return DIALOG_BODIES[kind] || GenericPriceBody
}
