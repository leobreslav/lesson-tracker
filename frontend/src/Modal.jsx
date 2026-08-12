import { useEffect, useRef } from 'react'

/**
 * Обёртка над нативным <dialog> в режиме showModal.
 *
 * Диалог рисуется в top layer и центрируется по области просмотра, поэтому
 * виден при любой прокрутке страницы. Escape и затемнение фона браузер
 * берёт на себя; клик мимо содержимого приходит на сам dialog (у .modal
 * нулевой padding, так что попасть в него можно только через фон).
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
