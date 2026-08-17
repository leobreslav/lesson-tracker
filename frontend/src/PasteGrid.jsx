import { useState } from 'react'
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
    <div className="paste-grid" onPaste={handlePaste}>
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
                <td key={name} className={name === 'id' ? 'id' : ''}>
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
