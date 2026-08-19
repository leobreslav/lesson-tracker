import { Fragment, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { parseDate, today } from './calendarLogic'
import { shortWeekday } from './dates'

/**
 * A week as a grid: lesson numbers down the side, days across the top.
 *
 * Used by both schedules — the teacher's own and the school-wide one. They
 * differ in what sits inside a cell and what a click does, not in the shape
 * of the week, so everything specific arrives as props:
 *
 * * `lessonsOn(date)` — what to draw, already filtered by the page;
 * * `renderLesson(lesson)` — the label inside the button;
 * * `isFree(cell)` — whether the «+» is offered on top of what is there
 *   (a cancelled lesson frees the hour without leaving the screen);
 * * `onPickDay` / `onOpen` / `onAdd` / `onMenu` — что значит нажатие.
 *
 * Нажатий по уроку два, и разделены они по частоте: **левое ведёт в само
 * занятие** — туда ходят каждый день, — а меню (отменить, перенести,
 * удалить ряд) висит на **правой кнопке**, потому что сетку правят реже,
 * чем по ней живут. Раньше левое открывало меню, и в занятие приходилось
 * заходить через его первый пункт: два нажатия там, где нужно ноль.
 *
 * На сенсорном экране правой кнопки нет, поэтому меню открывает **долгое
 * нажатие**: без него телефон потерял бы отмену и перенос целиком.
 *
 * Keeping one grid means a fix to the day header or the stacked-cell layout
 * lands on both pages at once, which is the whole reason it is here.
 */
export default function WeekGrid({
  dates,
  days,
  numbers,
  busy,
  selected = () => false,
  lessonsOn,
  renderLesson,
  lessonClassName,
  lessonTitle = () => undefined,
  isFree = () => true,
  onPickDay,
  onOpen,
  onAdd,
  onMenu,
}) {
  const { t } = useTranslation()

  /*
   * Долгое нажатие — то же меню, что и правая кнопка.
   *
   * На сенсорном экране правой кнопки нет, и без этого пути телефон
   * потерял бы отмену, перенос и удаление ряда целиком.
   *
   * Флаг «меню уже открыто долгим нажатием» снимается на **начале
   * следующего нажатия**, а не на клике, который его погасил. Разница
   * поймана тестом: после `touchend` браузер шлёт обычный `click`, и его
   * глушить надо; но если клика не случилось — меню закрыли с клавиатуры,
   * палец ушёл в сторону, — флаг оставался поднятым и съедал первое
   * честное нажатие. `pointerdown` приходит и от мыши, и от пальца, то
   * есть чинит оба случая разом.
   */
  const timer = useRef(null)
  const held = useRef(false)

  const press = (event, date, lesson) => {
    held.current = false
    if (event.pointerType !== 'touch') return

    clearTimeout(timer.current)
    // палец: меню встаёт там, где держали
    const at = { x: event.clientX, y: event.clientY }
    timer.current = setTimeout(() => {
      held.current = true
      onMenu?.(date, lesson, at)
    }, 500)
  }

  const release = () => clearTimeout(timer.current)

  const open = (date, lesson) => {
    // клик, рождённый отпусканием долгого нажатия: меню уже открыто
    if (held.current) return
    onOpen?.(date, lesson)
  }

  const dayHeadClass = (date) => {
    const day = days[date] || {}
    return (
      'day-head' +
      (day.is_study ? '' : ' locked') +
      (date === today() ? ' today' : '') +
      (selected(date) ? ' selected' : '')
    )
  }

  return (
    <div
      className="week-grid"
      style={{ gridTemplateColumns: `2.5rem repeat(${dates.length}, minmax(0, 1fr))` }}
    >
      <div className="corner" />
      {dates.map((date) => {
        const day = days[date] || {}
        return (
          <button
            type="button"
            key={date}
            data-day-head={date}
            className={dayHeadClass(date)}
            title={t('agenda.selectHint', {
              title: day.title || t('agenda.selectDay'),
            })}
            onClick={(event) => onPickDay?.(date, event)}
          >
            <span>{shortWeekday(date)}</span>
            <strong>{parseDate(date).getDate()}</strong>
            {!day.is_study && <em>{day.title || t('agenda.notStudy')}</em>}
          </button>
        )
      })}

      {numbers.map((number) => (
        <Fragment key={number}>
          <div className="row-head">{number}</div>
          {dates.map((date) => {
            const inCell = lessonsOn(date).filter(
              (item) => item.lesson_number === number,
            )
            const locked = !days[date]?.is_study

            if (!inCell.length && locked) {
              return <div key={date} className="cell locked" />
            }

            const addButton = (
              <button
                type="button"
                data-add={`${date}:${number}`}
                className={inCell.length ? 'cell free add-more' : 'cell free'}
                aria-label={t('agenda.addLesson', { number })}
                disabled={busy}
                onClick={() => onAdd?.(date, number)}
              >
                +
              </button>
            )

            if (!inCell.length) return <Fragment key={date}>{addButton}</Fragment>

            return (
              <div
                key={date}
                className={inCell.length > 1 ? 'cell-stack multi' : 'cell-stack'}
              >
                {inCell.map((lesson) => (
                  <button
                    type="button"
                    key={lesson.id}
                    data-lesson={`${date}:${number}`}
                    className={lessonClassName(lesson)}
                    title={lessonTitle(lesson)}
                    disabled={busy}
                    onClick={() => open(date, lesson)}
                    onContextMenu={(event) => {
                      // своё меню вместо браузерного: правая кнопка тут
                      // значит «что сделать с этим часом». Координаты едут
                      // с событием — меню открывается у курсора, а не
                      // посреди экрана
                      event.preventDefault()
                      onMenu?.(date, lesson, {
                        x: event.clientX,
                        y: event.clientY,
                      })
                    }}
                    onPointerDown={(event) => press(event, date, lesson)}
                    onPointerUp={release}
                    onPointerLeave={release}
                    onPointerCancel={release}
                  >
                    {renderLesson(lesson)}
                  </button>
                ))}
                {isFree(inCell) && !locked && addButton}
              </div>
            )
          })}
        </Fragment>
      ))}
    </div>
  )
}
