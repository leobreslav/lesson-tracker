import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * A wrapper around the native <dialog> in showModal mode.
 *
 * The dialog is painted in the top layer and centred on the viewport, so it
 * is visible however far the page is scrolled. Escape and the backdrop are
 * the browser's job; a click outside the content lands on the dialog itself
 * (.modal has zero padding, so the only way to hit it is through the
 * backdrop).
 *
 * **Крестик в углу — один на все окна, и живёт он здесь.** Уйти из окна и
 * до него было чем — Escape и клик по фону, — но оба беззвучны: ниоткуда не
 * видно, что они есть. Поэтому у окон стояла кнопка «Закрыть», и в тех, где
 * решать нечего, она занимала целую строку ряда действий ради выхода. В меню
 * урока это выглядело как «Открыть урок · Отменить · Перенести · Удалить ·
 * Закрыть» — четыре действия и одно не-действие в одном ряду.
 *
 * **«Отмена» в форме при этом остаётся, и это не непоследовательность.**
 * «Сохранить / Отмена» — вопрос и два ответа на него, и стоять они должны
 * рядом, в точке решения; крестик в дальнем углу как «нет, не надо» не
 * читается. Убрана только та кнопка, которая ничего не решала.
 *
 * `title` необязателен: у окна бывает свой заголовок сложнее строки — две
 * части в надзоре методиста. Тогда в шапке стоит один крестик, а заголовок
 * остаётся там, где его нарисовали.
 *
 * `actions` — то, что делают с окном целиком: «Сохранить», переключатель
 * режима. Стоят они там же, в строке заголовка, слева от крестика.
 *
 * Крестик уважает `onBeforeClose` наравне с Escape и фоном: три выхода из
 * одного окна должны вести себя одинаково, иначе несохранённое теряется
 * ровно тем из них, о котором забыли.
 */
export default function Modal({
  onClose,
  onBeforeClose,
  title = null,
  actions = null,
  className = '',
  children,
}) {
  const { t } = useTranslation()
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
      <div className={`modal-body ${className}`.trim()}>
        <div className="modal-head">
          {title !== null && <h3>{title}</h3>}
          {/* действия окна — в строке заголовка, рядом с крестиком: в
              окне-простыне подвал с одной кнопкой «Сохранить» уезжал вниз
              на длинном содержании, а переключатель «Правка/Просмотр» жил
              в третьем месте, отдельно от них обоих */}
          {actions && <span className="modal-actions">{actions}</span>}
          <button
            type="button"
            className="modal-close"
            aria-label={t('common.closeWindow')}
            title={t('common.closeWindow')}
            onClick={() => {
              if (mayClose()) onClose()
            }}
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}
