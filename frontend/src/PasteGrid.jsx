import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { parseClipboard } from './clipboardGrid'

/** Больше правят в самой таблице: это поле для вставки, а не редактор. */
export const PASTE_LIMIT = 500

const COLUMNS = ['id', 'Тема', 'Урок']
const BLANK = ['', '', '']

/**
 * Сетка для вставки из Excel.
 *
 * Замысел простой: вставили — и сразу видно, что тема попала в «Тему», а
 * урок в «Урок». Текстовое поле показало бы сырые табуляции, а «как файл
 * прочитан» пришлось бы объяснять отдельной строкой чисел; здесь это одно
 * и то же место.
 *
 * Колонку выбирает сам человек, курсором: скопировали две колонки без id —
 * встали в «Тему» и вставили туда. Никакого «назначения колонок» с
 * селектами поэтому нет, и не нужно.
 *
 * **Это не редактор таблиц, и обещать его нельзя.** Нет выделения
 * диапазонов, протягивания за угол, отмены на несколько шагов и ширины
 * колонок. Есть: вставка от выбранной ячейки, правка ячейки, удаление и
 * добавление строки. Всё остальное делают в Excel и вставляют заново.
 */
export default function PasteGrid({ rows, onChange, disabled = false }) {
  const { t } = useTranslation()
  const [tooBig, setTooBig] = useState(0)
  /*
   * Выделение прямоугольника мышью и Delete на нём.
   *
   * Единственное, что взято у настоящих таблиц: стереть кусок целиком
   * иначе значит щёлкать по ячейкам по одной. Тянут за ячейки, а не за
   * текст: пока курсор не вышел из ячейки, работает обычное выделение
   * текста внутри неё, и только выход за её край превращает жест в
   * выделение диапазона.
   *
   * Якорь живёт в ref, а не в состоянии: `mouseenter` приходит тем же
   * тактом, что `mousedown`, и состояние к этому моменту не обновилось бы.
   */
  const anchor = useRef(null)
  const [range, setRange] = useState(null) // {from: {row, column}, to}

  const shown = rows.length ? rows : [BLANK]

  const handlePaste = (event) => {
    const text = event.clipboardData?.getData('text/plain') ?? ''
    if (!text.includes('\t') && !text.includes('\n')) return // одна ячейка

    /*
     * Откуда вставлять, спрашиваем у самой ячейки, а не у состояния.
     *
     * Состояние обновляется после фокуса, а вставка приходит тем же
     * тактом: щёлкнули в «Тему» и сразу нажали Ctrl+V — и `at` ещё
     * показывал бы прошлую ячейку. У события есть цель, и на ней всё
     * написано.
     */
    const cell = event.target?.dataset ?? {}
    const at = { row: Number(cell.row ?? 0), column: Number(cell.column ?? 0) }

    event.preventDefault()
    let pasted = parseClipboard(text)
    if (!pasted.length) return

    // шапку узнаём дословно и в данные не пускаем: из таблицы копируют
    // по-разному, и требовать её от выделенного куска — требовать лишнего
    const head = pasted[0].map((cell) => cell.trim().toLowerCase())
    if (COLUMNS.every((name, index) => head[index] === name.toLowerCase())) {
      pasted = pasted.slice(1)
    }

    const next = shown.map((row) => [...row])
    pasted.forEach((cells, offset) => {
      const line = at.row + offset
      while (next.length <= line) next.push([...BLANK])
      cells.forEach((value, column) => {
        const target = at.column + column
        if (target < COLUMNS.length) next[line][target] = value
      })
    })

    if (next.length > PASTE_LIMIT) {
      setTooBig(next.length)
      return
    }

    setTooBig(0)
    onChange(next)
  }

  // тянуть можно в любую сторону, а прямоугольник всегда один
  const box = range && {
    top: Math.min(range.from.row, range.to.row),
    bottom: Math.max(range.from.row, range.to.row),
    left: Math.min(range.from.column, range.to.column),
    right: Math.max(range.from.column, range.to.column),
  }
  const picked = (line, column) =>
    Boolean(
      box &&
        line >= box.top &&
        line <= box.bottom &&
        column >= box.left &&
        column <= box.right,
    )

  const extend = (event, line, column) => {
    // кнопка отпущена — это просто движение мыши над таблицей
    if (event.buttons !== 1 || !anchor.current) return
    const start = anchor.current
    if (start.row === line && start.column === column) return

    // текст, выделившийся по дороге, тут только мешает — в том числе тот,
    // что выделился внутри поля: у него своё выделение, не документа
    window.getSelection?.()?.removeAllRanges()
    document.activeElement?.blur?.()
    setRange({ from: start, to: { row: line, column } })
  }

  const clearRange = () => {
    if (!box) return
    const next = shown.map((row) => [...row])
    for (let line = box.top; line <= box.bottom; line += 1) {
      for (let column = box.left; column <= box.right; column += 1) {
        if (next[line]) next[line][column] = ''
      }
    }
    onChange(next)
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') return setRange(null)
    if (event.key !== 'Delete' && event.key !== 'Backspace') return
    // одна ячейка — это обычная правка текста, и мешать ей нельзя
    if (!box || (box.top === box.bottom && box.left === box.right)) return

    event.preventDefault()
    clearRange()
  }

  // жест кончился — якорь снимаем, выделение остаётся: по нему ещё нажмут
  useEffect(() => {
    const done = () => {
      anchor.current = null
    }
    window.addEventListener('mouseup', done)
    return () => window.removeEventListener('mouseup', done)
  }, [])

  const edit = (line, column, value) => {
    const next = shown.map((row) => [...row])
    next[line][column] = value
    onChange(next)
  }

  const removeRow = (line) => {
    const next = shown.filter((_, index) => index !== line)
    onChange(next)
  }

  return (
    <div className="paste-grid" onPaste={handlePaste} onKeyDown={handleKeyDown}>
      <table>
        <thead>
          <tr>
            {COLUMNS.map((name) => (
              <th key={name} className={name === 'id' ? 'id' : ''}>
                {name}
              </th>
            ))}
            <th aria-hidden="true" />
          </tr>
        </thead>
        <tbody>
          {shown.map((row, line) => (
            // eslint-disable-next-line react/no-array-index-key
            <tr key={line}>
              {COLUMNS.map((name, column) => (
                <td
                  key={name}
                  className={
                    (name === 'id' ? 'id' : '') + (picked(line, column) ? ' picked' : '')
                  }
                  onMouseDown={() => {
                    anchor.current = { row: line, column }
                    setRange(null)
                  }}
                  onMouseEnter={(event) => extend(event, line, column)}
                >
                  <input
                    type="text"
                    value={row[column] ?? ''}
                    disabled={disabled}
                    aria-label={`${name} ${line + 1}`}
                    data-row={line}
                    data-column={column}
                    onChange={(event) => edit(line, column, event.target.value)}
                  />
                </td>
              ))}
              <td className="drop">
                <button
                  type="button"
                  className="link"
                  title={t('common.delete')}
                  disabled={disabled || shown.length === 1}
                  onClick={() => removeRow(line)}
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="row">
        <button
          type="button"
          className="secondary"
          disabled={disabled}
          onClick={() => onChange([...shown, [...BLANK]])}
        >
          {t('csv.paste.addRow')}
        </button>
        <span className="hint">{t('csv.paste.hint')}</span>
      </div>

      {tooBig > 0 && (
        <p className="error">{t('csv.paste.tooBig', { count: PASTE_LIMIT })}</p>
      )}
    </div>
  )
}
