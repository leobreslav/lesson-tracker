import { Fragment } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Один день как таблица: номера уроков сверху вниз, столбцы — по выбранной оси.
 *
 * Вторая сетка расписания школы, и заведена она не ради разнообразия видов.
 * Неделя (`WeekGrid.jsx`) кладёт в клетку **все** курсы, у которых в этот
 * день этот номер: у учителя их там один-два, а в школе первых уроков
 * примерно столько же, сколько курсов, — и понедельничная клетка «1»
 * превращается в стопку из полутора десятков строк ростом в экран. Читать
 * её невозможно, а поставить в неё час — тем более.
 *
 * Развернуть эту стопку и значит развернуть день **по столбцам**. По каким —
 * решает тот, кто смотрит (`dayAxis.js`): завуч, раскладывающий часы, видит
 * курсы; ищущий свободное помещение — кабинеты; ищущий, кем закрыть окно, —
 * учителей. Данные при этом одни и те же, и здесь про ось не знают ничего:
 * столбцы и раскладку считает страница.
 *
 * **Клетка держит стопку, и это не уступка.** На оси курсов час в ней ровно
 * один — `unique_together (course, date, lesson_number)` держит это
 * ограничением базы, — а на остальных стопка законна: в делимом зале два
 * занятия разом норма, у заменяющего учителя два часа в одном номере тоже
 * бывают. Сетка, умеющая показать один час, молча прятала бы второй.
 *
 * Платим шириной: девятнадцать столбцов — это таблица шире экрана, и она
 * прокручивается внутри своей коробки (страница вбок не едет — правило
 * общее для широких таблиц). Колонка номеров при этом прилипает к левому
 * краю: уехав вправо на четырнадцатый столбец, человек иначе не знает, в
 * каком он ряду.
 *
 * Чего здесь нет намеренно:
 *
 * * **перетаскивания.** В неделе оно переносит час на другой день или
 *   номер — то же, что «Перенести» в меню. Здесь соседний столбец это
 *   другой курс, кабинет или учитель, и жест обещал бы перенос, а значил
 *   бы «отдайте этот час другому», чего нет ни в API, ни в голове у того,
 *   кто тащит;
 * * **выделения дней.** Массовые операции идут по дням, а день тут один —
 *   его и копируют кнопкой в баре.
 *
 * Всё остальное — те же клетки, те же метки и то же меню, что в неделе:
 * один факт должен выглядеть одинаково на обоих видах, иначе они разъедутся
 * в первой же правке.
 */
export default function DayGrid({
  date,
  day = {},
  // столбцы считает страница (`dayAxis.columns`): здесь их только рисуют
  columns,
  numbers,
  busy,
  // часы этого столбца на этом номере — список: клетка держит стопку
  lessonsIn,
  renderLesson,
  lessonClassName,
  lessonTitle = () => undefined,
  onAdd,
  onMenu,
  bells = {},
}) {
  const { t } = useTranslation()

  const locked = !day.is_study

  /*
   * Меню встаёт у курсора — значит нужны координаты, а у нажатия с
   * клавиатуры их нет. Тот же приём и та же причина, что в неделе: дошедший
   * до клетки табуляцией иначе получил бы меню в левом верхнем углу.
   */
  const menuAt = (event) => {
    if (event.clientX || event.clientY) {
      return { x: event.clientX, y: event.clientY }
    }
    const cell = event.currentTarget.getBoundingClientRect()
    return { x: cell.left, y: cell.bottom }
  }

  if (!columns.length) {
    return (
      <p className="hint" role="status">
        {t('schoolSchedule.day.noCourses')}
      </p>
    )
  }

  return (
    <div className="day-sheet">
      <div
        className="day-grid"
        data-day={date}
        style={{
          gridTemplateColumns: `3rem repeat(${columns.length}, minmax(7.5rem, 1fr))`,
        }}
      >
        <div className="corner" />
        {columns.map((column) => (
          <div
            key={column.key}
            data-column={column.key}
            className={
              'day-column-head' +
              // столбец «не указан» и столбец того, кого в справочнике уже
              // нет: и то и другое — не норма, и подписаны они иначе
              (column.none || column.gone ? ' unassigned' : '')
            }
            title={[column.name, column.note].filter(Boolean).join(' — ')}
          >
            <strong>{column.name ?? t('schoolSchedule.day.none')}</strong>
            {/* вторая строка — то, что про столбец полезно знать и что не
                влезает в имя: кто ведёт курс, делимый ли зал. Внутри клеток
                этого нет: повторённое десять раз в одном столбце, оно
                закрыло бы собой сами часы */}
            <em>{column.note}</em>
          </div>
        ))}

        {numbers.map((number) => (
          <Fragment key={number}>
            {/* номер и время звонка под ним — тем же порядком, что в неделе */}
            <div className="row-head">
              <span>{number}</span>
              {bells[number] && (
                <em className="row-bell">
                  {bells[number].starts_at}
                  <br />
                  {bells[number].ends_at}
                </em>
              )}
            </div>

            {columns.map((column) => {
              const inCell = lessonsIn(column.key, number)

              const addButton = (
                <button
                  type="button"
                  data-add={`${date}:${number}:${column.key}`}
                  className={inCell.length ? 'cell free add-more' : 'cell free'}
                  aria-label={t('schoolSchedule.day.addTo', {
                    number,
                    column: column.name ?? t('schoolSchedule.day.none'),
                  })}
                  disabled={busy}
                  onClick={() => onAdd?.(date, number, column)}
                >
                  +
                </button>
              )

              if (!inCell.length) {
                // неучебный день не принимает часы — как и в неделе: молча
                // положить туда занятие значило бы завести урок в праздник
                // в обход того же запрета
                return locked ? (
                  <div key={column.key} className="cell locked" />
                ) : (
                  <Fragment key={column.key}>{addButton}</Fragment>
                )
              }

              return (
                <div
                  key={column.key}
                  className={inCell.length > 1 ? 'cell-stack multi' : 'cell-stack'}
                >
                  {inCell.map((lesson) => (
                    <button
                      type="button"
                      key={lesson.id}
                      /* ключ клетки — тройка, а не пара: пару «дата и номер»
                         в этом виде делят все столбцы, и по ней нельзя
                         указать ни на один час в отдельности */
                      data-lesson={`${date}:${number}:${column.key}`}
                      className={lessonClassName(lesson)}
                      title={lessonTitle(lesson)}
                      disabled={busy}
                      onClick={(event) => onMenu?.(date, lesson, menuAt(event))}
                      onContextMenu={(event) => {
                        // своё меню вместо браузерного — как в неделе: правое
                        // нажатие по часу значит ровно то же, что левое
                        event.preventDefault()
                        onMenu?.(date, lesson, menuAt(event))
                      }}
                    >
                      {renderLesson(lesson)}
                    </button>
                  ))}
                  {/* место свободно, пока в клетке одни отмены: тот же
                      признак, что и в неделе */}
                  {!locked &&
                    !inCell.some((lesson) => !lesson.is_cancelled) &&
                    addButton}
                </div>
              )
            })}
          </Fragment>
        ))}
      </div>
    </div>
  )
}
