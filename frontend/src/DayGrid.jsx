import { Fragment } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Один день как таблица: номера уроков сверху вниз, курсы слева направо.
 *
 * Вторая сетка расписания школы, и заведена она не ради разнообразия видов.
 * Неделя (`WeekGrid.jsx`) кладёт в клетку **все** курсы, у которых в этот
 * день этот номер: у учителя их там один-два, а в школе первых уроков
 * примерно столько же, сколько курсов, — и понедельничная клетка «1»
 * превращается в стопку из полутора десятков строк ростом в экран. Читать
 * её невозможно, а поставить в неё час — тем более.
 *
 * Развернуть эту стопку и значит развернуть **курс в отдельный столбец**:
 * тогда пересечение «курс × номер» — ровно одна клетка, и она пустая или
 * занятая. Не «почти одна»: `unique_together (course, date, lesson_number)`
 * держит это ограничением базы, и стопок здесь не бывает по построению.
 *
 * Платим шириной: девятнадцать курсов — это таблица шире экрана, и она
 * прокручивается внутри своей коробки (страница вбок не едет — правило
 * общее для широких таблиц). Колонка номеров при этом прилипает к левому
 * краю: уехав вправо на четырнадцатый курс, человек иначе не знает, в
 * каком он ряду.
 *
 * Чего здесь нет намеренно:
 *
 * * **перетаскивания.** В неделе оно переносит час на другой день или
 *   номер — то же, что «Перенести» в меню. Здесь соседний столбец это
 *   **другой курс**, а час принадлежит курсу: жест обещал бы перенос, а
 *   значил бы «отдайте этот урок другому классу», чего нет ни в API, ни в
 *   голове у того, кто тащит;
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
  courses,
  numbers,
  busy,
  // час курса на этом номере — или ничего. Ищет страница: она же знает,
  // что показано, а что убрано фильтром
  lessonAt,
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

  if (!courses.length) {
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
          gridTemplateColumns: `3rem repeat(${courses.length}, minmax(7.5rem, 1fr))`,
        }}
      >
        <div className="corner" />
        {courses.map((course) => {
          const leads = (course.teachers ?? []).map((teacher) => teacher.name)

          return (
            <div
              key={course.id}
              data-course-head={course.id}
              className={leads.length ? 'day-course-head' : 'day-course-head unassigned'}
              title={[course.name, leads.join(', ')].filter(Boolean).join(' — ')}
            >
              <strong>{course.name}</strong>
              {/* кто ведёт — здесь же, а не в клетке: в неделе имя стоит в
                  каждом часе, потому что курсов в клетке несколько, а тут
                  столбец и есть курс, и повторённое десять раз имя
                  заслоняло бы сами часы */}
              <em>{leads.join(', ') || t('schoolSchedule.nobody')}</em>
            </div>
          )
        })}

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

            {courses.map((course) => {
              const lesson = lessonAt(course.id, number)

              if (!lesson) {
                if (locked) {
                  return <div key={course.id} className="cell locked" />
                }

                return (
                  <button
                    type="button"
                    key={course.id}
                    data-add={`${date}:${number}:${course.id}`}
                    className="cell free"
                    aria-label={t('schoolSchedule.day.addTo', {
                      number,
                      course: course.name,
                    })}
                    disabled={busy}
                    onClick={() => onAdd?.(date, number, course.id)}
                  >
                    +
                  </button>
                )
              }

              return (
                <button
                  type="button"
                  key={course.id}
                  /* ключ клетки — тройка, а не пара: пару «дата и номер»
                     в этом виде делят все столбцы, и по ней нельзя указать
                     ни на один час в отдельности */
                  data-lesson={`${date}:${number}:${course.id}`}
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
              )
            })}
          </Fragment>
        ))}
      </div>
    </div>
  )
}
