import { useEffect, useRef } from 'react'

/**
 * A wrapper around the native <dialog> in showModal mode.
 *
 * The dialog is painted in the top layer and centred on the viewport, so it
 * is visible however far the page is scrolled. Escape and the backdrop are
 * the browser's job; a click outside the content lands on the dialog itself
 * (.modal has zero padding, so the only way to hit it is through the
 * backdrop).
 */
export default function Modal({ onClose, onBeforeClose, className = '', children }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    dialogRef.current.showModal()
  }, [])

  /** A guard for windows holding unsaved work. Absent means «just close». */
  const mayClose = () => !onBeforeClose || onBeforeClose()

  return (
    <dialog
      ref={dialogRef}
      className={`modal ${className}`.trim()}
      onClose={onClose}
      // Escape fires `cancel` before `close`, which is the only moment a
      // window with unsaved changes can still stop itself from vanishing
      onCancel={(event) => {
        if (!mayClose()) event.preventDefault()
      }}
      onClick={(event) => {
        if (event.target === dialogRef.current && mayClose()) onClose()
      }}
    >
      <div className={`modal-body ${className}`.trim()}>{children}</div>
    </dialog>
  )
}
