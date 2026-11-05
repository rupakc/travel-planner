// Price-watch dialog: the kind-specific part of the body (the shell, alert
// mode, email and no-live-price suggestions are shared: ../PriceWatchDialog).
// Add a kind by creating its body in this folder and one line below, e.g.
//   import HotelDialogBody from './HotelDialogBody'   →   hotel: HotelDialogBody,
// Bodies get { kind, spec, preview, watch, unitLabel, onClose } (see GenericPriceBody;
// onClose closes the dialog, e.g. before a link leaves the page).
import GenericPriceBody from './GenericPriceBody'
import ActivityDialogBody from './ActivityDialogBody'
import HotelDialogBody from './HotelDialogBody'

export const DIALOG_BODIES = {
  activity: ActivityDialogBody,
  hotel: HotelDialogBody,
}

export function dialogBodyFor(kind) {
  return DIALOG_BODIES[kind] || GenericPriceBody
}
