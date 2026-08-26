import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Клетка журнала под правкой: поле там, где только что стоял текст.
 *
 * **Полем становится ровно одна клетка — та, на которой курсор.** Остальные
 * остаются текстом, и это не экономия разметки, а требование заказчика,
 * названное прямо: тысяча маленьких полей превращает журнал в бланк, который
 * читать нельзя. Поэтому поле рисуется в размер своей подколонки, тем же
 * кеглем и по центру, без рамки — снаружи это та же клетка, просто с
 * кареткой.
 *
 * **Меню полос рядом, а не вместо ввода.** У работы обычно выбрана система
 * оценивания, и её полосы — те самые четыре-семь значений, которыми учитель
 * пользуется девяносто девять раз из ста: тыкнуть быстрее, чем набрать. Но
 * свободный ввод остаётся: «н/а», «осв» и прочее в полосы не входит, а
 * запрещать их дороже, чем разрешить — поле у работы ученика и так строка на
 * сорок знаков.
 *
 * Пустой пункт в меню — не «ничего», а **снять отметку**: пустая строка
 * возвращает работу системе (`services.grade`), и это не то же самое, что
 * ноль. Ноль бывает отметкой.
 *
 * Клавиши те, которых ждут от таблицы: Enter записывает и уводит вниз (журнал
 * заполняют по работе, весь класс подряд), Tab — вправо, Esc отменяет.
 */
export default function JournalCell({
  value,
  options,
  title,
  onCommit,
  onCancel,
  busy = false,
}) {
  const { t } = useTranslation()
  const [text, setText] = useState(value ?? '')
  const field = useRef(null)

  useEffect(() => {
    field.current?.focus()
    field.current?.select()
  }, [])

  const keys = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onCommit(text, 'down')
    } else if (event.key === 'Tab') {
      event.preventDefault()
      onCommit(text, 'right')
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onCancel()
    }
  }

  return (
    <span className="cell-editor">
      <input
        ref={field}
        className="cell-input"
        value={text}
        maxLength={40}
        disabled={busy}
        aria-label={title}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={keys}
        /* уход из клетки — тоже запись: человек кликнул в соседнюю, и
           потерять набранное на этом было бы худшим из исходов. Отмена
           остаётся у Esc, где её и ищут */
        onBlur={() => onCommit(text, 'stay')}
      />

      {options.length > 0 && (
        /* Меню держится на `onMouseDown`, а не на `onClick`: клик по кнопке
           сначала уводит фокус из поля, то есть срабатывает запись по уходу —
           и пункт меню нажимался бы уже по закрытой клетке. */
        <span className="cell-menu" role="listbox" aria-label={title}>
          {options.map((one) => (
            <button
              key={one}
              type="button"
              role="option"
              aria-selected={one === text}
              className={one === text ? 'on' : ''}
              onMouseDown={(event) => {
                event.preventDefault()
                onCommit(one, 'down')
              }}
            >
              {one}
            </button>
          ))}
          <button
            type="button"
            className="clear"
            onMouseDown={(event) => {
              event.preventDefault()
              onCommit('', 'stay')
            }}
          >
            {t('journal.clearMark')}
          </button>
        </span>
      )}
    </span>
  )
}
