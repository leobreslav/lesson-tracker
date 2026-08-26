import { Fragment } from 'react'
import {
  DndContext,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
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
 * **Занятие переносится перетаскиванием**, если страница дала `onDrop`.
 * Жест это ускоритель, а не единственный путь: то же самое делает «Перенести»
 * в меню, и оно остаётся — с клавиатуры, с читалкой и там, где тащить неудобно,
 * работает только оно. Заводить второй способ вместо первого было бы обменом
 * доступности на скорость.
 *
 * Два решения, без которых жест мешал бы работе:
 *
 * * **порог в пять пикселей** (`PointerSensor`) и **задержка на касании**.
 *   Нажатие по занятию открывает меню, и без порога любое нажатие с дрожью
 *   руки превращалось бы в перенос — то есть в правку расписания вместо
 *   разговора о нём;
 * * **неучебный день не принимает**. На нём и «+» не предлагается: клетка
 *   заперта, и молча положить туда занятие значило бы завести урок в
 *   праздник в обход того же запрета.
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
  onDrop,
  bells = {},
}) {
  const { t } = useTranslation()

  const sensors = useSensors(
    // порог: без него нажатие «открыть меню» и перетаскивание неразличимы
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 200, tolerance: 6 },
    }),
  )

  const drop = ({ active, over, activatorEvent, delta }) => {
    if (!over || !onDrop) return
    const [date, number] = String(over.id).replace('cell:', '').split(':')
    const from = active.data.current
    if (!from) return
    // то же место — не перенос: сервер принял бы, но занятие уехало бы в
    // отмену и вернулось на ту же клетку, оставив ложный след
    if (from.date === date && String(from.lesson.lesson_number) === number) return
    onDrop(from.lesson, from.date, { date, lesson_number: Number(number) }, dropAt(activatorEvent, delta))
  }

  /*
   * Где отпустили — в координатах экрана.
   *
   * Спрашивать после броска есть о чём: перенос бывает разовым и
   * постоянным, и вопрос должен встать там же, где рука. Своей точки у
   * `onDragEnd` нет — есть место **начала** жеста и пройденный путь, и
   * сумма их и есть место, где палец отпустили.
   *
   * У жеста с клавиатуры координат нет вовсе (`clientX` там ноль), и тогда
   * берётся центр окна: меню посреди экрана лучше меню в его углу. Тот же
   * довод, что у меню клетки рядом.
   */
  const dropAt = (event, delta) => {
    const x = event?.clientX ?? 0
    const y = event?.clientY ?? 0
    if (!x && !y) return { x: window.innerWidth / 2, y: window.innerHeight / 2 }
    return { x: x + (delta?.x ?? 0), y: y + (delta?.y ?? 0) }
  }

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

  const grid = (
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
          {/* Номер и, если школа завела звонки, время под ним. Время
              подписывает **строку**, а не каждую клетку: оно одно на весь
              ряд, и повторённое семь раз оно закрыло бы собой расписание.
              Звонков нет — ряд выглядит как раньше, одним номером. */}
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
          {dates.map((date) => {
            const inCell = lessonsOn(date).filter(
              (item) => item.lesson_number === number,
            )
            const locked = !days[date]?.is_study

            if (!inCell.length && locked) {
              return <div key={date} className="cell locked" />
            }

            // клетка принимает занятие только там, где перенос разрешён:
            // без `onDrop` обёртка не нужна и лишнего узла в сетке не будет
            const inDrop = (content) =>
              onDrop ? (
                <DropCell key={date} date={date} number={number} locked={locked}>
                  {content}
                </DropCell>
              ) : (
                <Fragment key={date}>{content}</Fragment>
              )

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

            if (!inCell.length) return inDrop(addButton)

            const Lesson = onDrop ? DraggableLesson : PlainLesson

            return inDrop(
              <div
                className={inCell.length > 1 ? 'cell-stack multi' : 'cell-stack'}
              >
                {inCell.map((lesson) => (
                  <Lesson
                    key={lesson.id}
                    lesson={lesson}
                    date={date}
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
                  </Lesson>
                ))}
                {isFree(inCell) && !locked && addButton}
              </div>,
            )
          })}
        </Fragment>
      ))}
    </div>
  )

  // Контекст заводится только там, где перенос разрешён: страница, не давшая
  // `onDrop`, получает прежнюю сетку без единого обработчика.
  return onDrop ? (
    <DndContext sensors={sensors} onDragEnd={drop}>
      {grid}
    </DndContext>
  ) : (
    grid
  )
}

/**
 * Клетка, принимающая занятие.
 *
 * Обёртка, а не `useDroppable` в теле сетки: хуки нельзя звать в цикле, а
 * клеток в неделе полсотни.
 */
function DropCell({ date, number, locked, children }) {
  const { isOver, setNodeRef } = useDroppable({
    id: `cell:${date}:${number}`,
    disabled: locked,
  })

  return (
    <div ref={setNodeRef} className={isOver && !locked ? 'cell-drop over' : 'cell-drop'}>
      {children}
    </div>
  )
}

/** Занятие без перетаскивания: та же кнопка, что была до жеста. */
function PlainLesson({ lesson, date, children, ...rest }) {
  return (
    <button type="button" {...rest}>
      {children}
    </button>
  )
}

/**
 * Занятие, которое можно взять.
 *
 * Кнопка остаётся кнопкой: нажатие открывает меню, и перетаскивание её не
 * заменяет — сенсор отдаёт нажатие форме, пока палец не проехал пять
 * пикселей.
 */
function DraggableLesson({ lesson, date, children, ...rest }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `slot:${lesson.id}`,
    data: { lesson, date },
  })

  return (
    <button
      ref={setNodeRef}
      type="button"
      {...rest}
      {...listeners}
      {...attributes}
      className={`${rest.className || ''}${isDragging ? ' dragging' : ''}`}
    >
      {children}
    </button>
  )
}
