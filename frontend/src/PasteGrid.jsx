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
  const dragging = useRef(false)
  const scroll = useRef(null)
  const auto = useRef(null) // таймер докрутки, пока курсор за краем
  const [range, setRange] = useState(null) // {from: {row, column}, to}

  const shown = rows.length ? rows : [BLANK]
  // жест живёт вне рендера: обработчики на окне читают свежее из ref
  const live = useRef({ range: null, lines: 1 })
  live.current = { range, lines: shown.length }

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
    if (event.buttons !== 1 || !dragging.current || !range) return
    if (range.to.row === line && range.to.column === column) return

    /*
     * Текст, выделившийся по дороге, тут только мешает — но **гасим его, а
     * не фокус**. Фокус остаётся на ячейке, с которой начали: клавиатура
     * приходит именно туда, и Delete на выделенном куске ловится обработчиком
     * таблицы. Пока поле снималось с фокуса, нажатие уходило в `body` мимо
     * неё, и кнопка «не работала».
     */
    window.getSelection?.()?.removeAllRanges()
    const focused = document.activeElement
    focused?.setSelectionRange?.(0, 0)

    setRange({ ...range, to: { row: line, column } })
    reveal(line)
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

  /**
   * Подвести к видимой части: выделение ушло за край — таблица едет следом.
   *
   * Иначе жест кончается вслепую: тянут мышью вниз, а строки стоят; жмут
   * Shift со стрелкой — подвижный конец уезжает под нижний край, и куда он
   * уехал, не видно. `scrollIntoView` у ячейки прокрутил бы и всё окно, а
   * ехать должен только внутренний ящик.
   */
  const reveal = (line, column = null) => {
    const box = scroll.current
    const row = box?.querySelectorAll('tbody tr')[line]
    if (!box || !row) return

    /*
     * Клавиатуре мало прокрутки — ей нужен переезд фокуса.
     *
     * Пока фокус оставался в той ячейке, с которой начали, браузер на
     * каждое нажатие возвращал её в поле зрения и отматывал прокрутку
     * обратно к нулю: мы уезжали вниз, он тащил наверх. Поэтому подвижный
     * конец забирает фокус себе, а выделение по-прежнему держит состояние.
     */
    if (column !== null) {
      row.querySelector(`input[data-column="${column}"]`)?.focus()
    }

    // шапка липкая и висит поверх строк: подводить надо под неё
    const head = box.querySelector('thead')?.getBoundingClientRect().height ?? 0
    const view = box.getBoundingClientRect()
    const cell = row.getBoundingClientRect()

    if (cell.top < view.top + head) box.scrollTop -= view.top + head - cell.top
    if (cell.bottom > view.bottom) box.scrollTop += cell.bottom - view.bottom
  }

  /** Растянуть выделение клавишами: якорь стоит, двигается второй конец. */
  const step = (event) => {
    const shift = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }
    const move = shift[event.key]
    if (!move) return false

    const from = range?.from ?? { row: 0, column: 0 }
    const to = range?.to ?? from
    const next = {
      row: Math.min(Math.max(to.row + move[0], 0), shown.length - 1),
      column: Math.min(Math.max(to.column + move[1], 0), COLUMNS.length - 1),
    }

    event.preventDefault()
    window.getSelection?.()?.removeAllRanges()
    setRange({ from, to: next })
    reveal(next.row, next.column)
    return true
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') return setRange(null)

    // Shift со стрелками тянет выделение по ячейкам. Внутри поля Shift+←
    // выделял бы текст, но выделять текст мышью никто не мешает, а вот
    // растянуть кусок с клавиатуры иначе нечем
    if (event.shiftKey && step(event)) return

    if (event.key !== 'Delete' && event.key !== 'Backspace') return
    // одна ячейка — это обычная правка текста, и мешать ей нельзя
    if (!box || (box.top === box.bottom && box.left === box.right)) return

    event.preventDefault()
    clearRange()
  }

  /*
   * Курсор ушёл за край — таблица докручивается сама.
   *
   * Строки, выехавшие из-под нижнего края, `mouseenter` не получают: курсор
   * снаружи ящика, и выделение переставало расти на полпути. Поэтому пока
   * кнопка держится за краем, таблица едет и подвижный конец идёт за ней —
   * по строке за такт, как в любой таблице.
   *
   * Обработчики висят на окне и читают состояние из ref: жест продолжается
   * там, где React уже ничего не перерисовывает.
   */
  useEffect(() => {
    const stop = () => {
      clearInterval(auto.current)
      auto.current = null
    }

    const creep = (down) => {
      if (auto.current) return
      auto.current = setInterval(() => {
        const { range: current, lines } = live.current
        if (!current || !dragging.current) return stop()

        const row = Math.min(Math.max(current.to.row + (down ? 1 : -1), 0), lines - 1)
        if (row === current.to.row) return stop()

        setRange({ ...current, to: { ...current.to, row } })
        reveal(row)
      }, 90)
    }

    const track = (event) => {
      const box = scroll.current
      if (!dragging.current || !box) return stop()

      const view = box.getBoundingClientRect()
      if (event.clientY > view.bottom) return creep(true)
      if (event.clientY < view.top) return creep(false)
      stop()
    }

    const done = () => {
      dragging.current = false
      stop()
    }

    window.addEventListener('mousemove', track)
    window.addEventListener('mouseup', done)
    return () => {
      window.removeEventListener('mousemove', track)
      window.removeEventListener('mouseup', done)
      stop()
    }
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
      {/* прокручивается только таблица: кнопка «добавить строку» уезжала
          вместе с ней и на длинной вставке пряталась под нижним краем */}
      <div className="paste-scroll" ref={scroll}>
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
                    dragging.current = true
                    // одна ячейка — это уже выделение из одной ячейки:
                    // от неё считаются и стрелки с Shift, и протягивание
                    setRange({
                      from: { row: line, column },
                      to: { row: line, column },
                    })
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
      </div>

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
