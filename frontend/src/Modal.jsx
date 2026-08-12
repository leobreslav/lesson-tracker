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
export default function Modal({ onClose, children }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    dialogRef.current.showModal()
  }, [])

  return (
    <dialog
      ref={dialogRef}
      className="modal"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialogRef.current) onClose()
      }}
    >
      <div className="modal-body">{children}</div>
    </dialog>
  )
}
