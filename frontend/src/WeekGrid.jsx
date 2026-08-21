import { Fragment } from 'react'
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
 * * `onPickDay` / `onAdd` / `onMenu` — что значит нажатие.
 *
 * **Нажатие по уроку одно, и любое из них открывает меню.** Левое, правое,
 * палец по экрану — один ответ, и в занятие ведёт первый пункт меню.
 *
 * Разделены они были по частоте: левое вело прямо в занятие, потому что
 * туда ходят каждый день, а меню (отменить, перенести, удалить ряд) висело
 * на правой кнопке. Считалось это экономией нажатия, а обошлось дороже:
 * правая кнопка ничем себя не показывает, и человек, который её не пробовал,
 * не знал про отмену и перенос вовсе — то есть половина работы с сеткой
 * просто не находилась. Подпись под сеткой этого не чинит: её читают один
 * раз и не запоминают. На телефоне же правой кнопки нет совсем, и всё это
 * держалось на долгом нажатии, о котором догадаться ещё труднее.
 *
 * Цена названа прямо: в занятие теперь два нажатия вместо одного. Первый
 * пункт меню — «Открыть урок», и стоит он первым как раз поэтому.
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
  onAdd,
  onMenu,
}) {
  const { t } = useTranslation()

  /*
   * Меню встаёт у курсора, а не посреди экрана, — значит нужны координаты.
   *
   * У нажатия с клавиатуры их нет: `clientX` там ноль, и меню уехало бы в
   * левый верхний угол — то есть человек, дошедший до клетки табуляцией,
   * получил бы меню в другом конце экрана. Тогда координаты берутся у самой
   * клетки: место нажатия известно и без курсора.
   */
  const menuAt = (event) => {
    if (event.clientX || event.clientY) {
      return { x: event.clientX, y: event.clientY }
    }
    const cell = event.currentTarget.getBoundingClientRect()
    return { x: cell.left, y: cell.bottom }
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
                    onClick={(event) => onMenu?.(date, lesson, menuAt(event))}
                    onContextMenu={(event) => {
                      // своё меню вместо браузерного, и то же самое, что у
                      // левой кнопки: правое нажатие по клетке календаря
                      // значит ровно то же — «что сделать с этим часом»
                      event.preventDefault()
                      onMenu?.(date, lesson, menuAt(event))
                    }}
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
