import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LessonMenu, RepeatChoice } from './AgendaDialogs'
import CopyDialog from './CopyDialog'
import DayGrid from './DayGrid'
import EmptyState from './EmptyState'
import Modal from './Modal'
import Switch from './Switch'
import WeekGrid from './WeekGrid'
import {
  deleteSlots,
  copySlots,
  createSlot,
  deleteSlot,
  fetchCourses,
  fetchSchoolSlots,
  fetchScheduleSummary,
  fetchMembers,
  fetchSchoolYears,
  fetchYearDays,
  moveSlot,
  repeatSlot,
  updateSlot,
} from './api'
import {
  addDays,
  eachDate,
  endOfWeek,
  startOfWeek,
  today,
} from './calendarLogic'
import { dateRange, firstWeekday, longDate } from './dates'
import { weekdayIndex } from './weekStart'
import { useKept } from './remember'
import { MAX_LESSON_NUMBER } from './scheduleLogic'
import {
  courseMatches,
  emptyFilters,
  filterOptions,
  pick,
  reconcile,
  slotMatches,
} from './scheduleFilters'

const NUMBERS = Array.from({ length: MAX_LESSON_NUMBER }, (_, index) => index + 1)

/**
 * The school-wide timetable, kept by administrators.
 *
 * The same week grid as «My schedule» — one component, so the two screens
 * cannot drift apart — with the teacher's name in the cell instead of the
 * topic, and filters that a personal schedule has no use for.
 *
 * **Размаха два: неделя и день.** Неделя отвечает на «как стоит расписание»,
 * и клетка в ней — это окно «день × номер», куда попадают все курсы разом. У
 * учителя их там один-два, а в школе первых уроков примерно столько же,
 * сколько курсов: понедельничная клетка «1» становится стопкой в полтора
 * десятка строк, которую нельзя ни прочитать, ни пополнить.
 *
 * День отвечает на «что происходит сегодня» и разворачивает ту самую стопку
 * — **курс в столбец** (`DayGrid.jsx`). Пересечение «курс × номер» тогда
 * ровно одна клетка: `unique_together (course, date, lesson_number)` держит
 * это ограничением базы. Платим шириной — таблица уезжает за экран и
 * прокручивается внутри своей коробки.
 *
 * Размах живёт в адресе (`?span=day`, см. `Schedule.jsx`), а не в состоянии
 * страницы: тем же доводом, что и школьный вид, — ссылкой делятся, а «назад»
 * из занятия возвращает туда, откуда ушли.
 */
export default function SchoolSchedule({
  views = null,
  span = 'week',
  onSpan = null,
  onLoggedOut,
}) {
  const { t } = useTranslation()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [courses, setCourses] = useState([])
  const [members, setMembers] = useState([])
  const [slots, setSlots] = useState([])
  const [days, setDays] = useState({})
  const [summary, setSummary] = useState(null)
  /*
   * Неделя и сужение переживают уход отсюда (`remember.useKept`).
   *
   * Отсюда уходят в занятие и возвращаются «назад» браузером: страница
   * собирается заново, и неделя вместе с выбранным учителем терялись — а
   * ради них сюда и заходили. Живёт это во вкладке, а не в настройках.
   */
  const [anchor, setAnchor] = useKept('school.schedule.week', today())
  /*
   * Три уровня сужения — одним значением, а не тремя.
   *
   * Выбор на одном уровне меняет соседние (`pick`), и разложенные по трём
   * ключам они писались бы тремя вызовами подряд — то есть промежуточное
   * состояние, в котором учитель уже новый, а курс ещё старый, попадало бы
   * в хранилище. Здесь состояние одно, и оно всегда согласовано.
   */
  const [chosen, setChosen] = useKept('school.schedule.filters', emptyFilters())
  const [dialog, setDialog] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const weekStart = firstWeekday()
  const byDay = span === 'day'
  /*
   * Показанный период считается от размаха, а не от нажатой стрелки: сетка,
   * стрелки, копирование и запрос за часами обязаны говорить об одном и том
   * же куске календаря, и второе место, где это решается, разошлось бы с
   * первым в ближайшую правку.
   */
  const period = useMemo(
    () =>
      byDay
        ? { start: anchor, end: anchor }
        : { start: startOfWeek(anchor, weekStart), end: endOfWeek(anchor, weekStart) },
    [byDay, anchor, weekStart],
  )
  const dates = useMemo(
    () => eachDate(period.start, period.end),
    [period.start, period.end],
  )

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    Promise.all([fetchSchoolYears(), fetchMembers()])
      .then(([yearList, people]) => {
        setYears(yearList)
        setMembers(people)
        setYearId((current) => current ?? yearList[0]?.id ?? null)
        if (yearList[0]) setAnchor((now) => clampToYear(now, yearList[0]))
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    if (!yearId) return
    // расписание школы — экран администратора: здесь нужны все курсы
    // школы, а не только те, что ведёт он сам
    fetchCourses(yearId, { scope: 'school' }).then(setCourses).catch(handleError)
    // the calendar decides which columns are dimmed; the timetable itself
    // knows nothing about breaks
    fetchYearDays(yearId)
      .then((data) =>
        setDays(Object.fromEntries(data.days.map((day) => [day.date, day]))),
      )
      .catch(handleError)
  }, [yearId, handleError])

  const load = useCallback(() => {
    if (!yearId) return Promise.resolve()

    return Promise.all([
      fetchSchoolSlots({ year: yearId, start: period.start, end: period.end }),
      fetchScheduleSummary({ year: yearId }),
    ])
      .then(([rows, totals]) => {
        setSlots(rows)
        setSummary(totals)
      })
      .catch(handleError)
  }, [yearId, period.start, period.end, handleError])

  useEffect(() => {
    load()
  }, [load])

  /*
   * Сохранённый выбор сверяется с приехавшими курсами: за время отсутствия
   * курс могли удалить, а ведущего — сменить. Считается это на лету, а
   * записывается при следующем выборе: лишний `setState` в отрисовке ради
   * состояния, которое и так не показывается, того не стоит.
   */
  const filters = useMemo(() => reconcile(courses, chosen), [courses, chosen])
  const options = useMemo(
    () => filterOptions(courses, members, filters),
    [courses, members, filters],
  )
  const courseById = useMemo(
    () => new Map(courses.map((course) => [course.id, course])),
    [courses],
  )
  const choose = (level) => (event) =>
    setChosen(pick(courses, filters, level, event.target.value))

  const visible = useMemo(
    () => slots.filter((slot) => slotMatches(slot, courseById, filters)),
    [slots, courseById, filters],
  )

  const lessonsOn = (date) => visible.filter((slot) => slot.date === date)

  /*
   * Столбцы дневного вида — курсы, и те же, что прошли сужение.
   *
   * Курс без единого часа в этот день столбец всё равно получает, и это не
   * недосмотр: пустой столбец — то место, куда час ставят. Спрятать его
   * значило бы спрятать половину работы администратора, ради которой он
   * сюда и заходит.
   */
  const columns = useMemo(
    () => courses.filter((course) => courseMatches(course, filters)),
    [courses, filters],
  )

  /*
   * Час курса на этом номере — не более одного: `unique_together
   * (course, date, lesson_number)`. Стопок, как в недельной клетке, тут не
   * бывает по построению.
   */
  const lessonAt = (courseId, number) =>
    visible.find(
      (slot) =>
        slot.date === period.start &&
        slot.course === courseId &&
        slot.lesson_number === number,
    ) ?? null

  /**
   * Как выглядит час — один ответ на обе сетки.
   *
   * Отменённый и дополнительный час выглядят тут так же, как у учителя. Не
   * выглядели вовсе: отменить из этой сетки было нечем, и никто не замечал,
   * что перечёркнутых часов она не рисует, — то есть администратор видел
   * сорванное занятие как обычное. Метки те же: записанный час — галочка,
   * прошедший без записи — красная точка.
   */
  const cellClass = (slot) =>
    (slot.teacher ? 'cell lesson' : 'cell lesson unassigned') +
    (slot.is_cancelled ? ' cancelled' : '') +
    (slot.is_extra ? ' extra' : '') +
    (slot.lesson ? ' recorded' : '') +
    (slot.debt ? ' debt' : '')

  const cellTitle = (slot) =>
    [slot.course_name, slot.teacher_name, slot.lesson_title]
      .filter(Boolean)
      .join(' — ')

  const run = async (request, describe) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await request()
      await load()
      if (describe) setNotice(describe(result))
      setDialog(null)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const addSlot = ({ step, until, ...fields }) =>
    run(() =>
      /* ряд уроков считает сервер: сколько дат съедят каникулы и сколько
         мест занято, знает только он */
      step
        ? repeatSlot({
            date: dialog.date,
            lesson_number: dialog.number,
            step,
            until,
            ...fields,
          })
        : createSlot({
            year: yearId,
            date: dialog.date,
            lesson_number: dialog.number,
            ...fields,
          }),
    )

  const removeSlot = (slot) => run(() => deleteSlot(slot.id))

  /**
   * Удаление ряда: этот час и все такие же до конца года.
   *
   * «Очистить период» тут было, и администратору оно годилось меньше всех:
   * он раскатывает сетку на год, а промахнувшись рядом, сносил бы период
   * целиком — вместе с чужими часами, которые в нём стоят.
   */
  const removeRow = (date, slot) =>
    run(
      () =>
        deleteSlots({
          classId: slot.course,
          start: date,
          end: (years ?? []).find((year) => year.id === yearId)?.end_date ?? date,
          weekday: weekdayIndex(date),
          number: slot.lesson_number,
          onlyRegular: true,
        }),
      (result) =>
        t('agenda.deletedRow', { count: result.deleted }) +
        (result.kept ? ' ' + t('agenda.keptRecorded', { count: result.kept }) : ''),
    )

  if (years === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  if (!years.length) {
    return (
      <main className="page narrow">
        <header className="page-header">
          <h1>{t('schoolSchedule.title')}</h1>
          {views}
        </header>
        <EmptyState title={t('school.courses.needYear')}>
          {t('school.year.hint')}
        </EmptyState>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('schoolSchedule.title')}</h1>
        {/* тумблер вида — тот же, что на своей неделе: страница одна */}
        {views}
      </header>

      <p className="hint">{t('schoolSchedule.hint')}</p>

      {summary && (
        <p className="hint">
          {t('schoolSchedule.summary', {
            total: summary.total,
            teachers: summary.teachers,
          })}
          {summary.unassigned > 0 && (
            <>
              {' · '}
              <strong>
                {t('schoolSchedule.unassigned', { count: summary.unassigned })}
              </strong>
            </>
          )}
        </p>
      )}

      <div className="agenda-bar">
        {/* шаг стрелки — показанный кусок целиком: в неделе неделя, в дне
            день. Иначе стрелка в дневном виде листала бы мимо шести дней */}
        <button
          type="button"
          className="secondary"
          onClick={() => setAnchor(addDays(anchor, byDay ? -1 : -7))}
        >
          ←
        </button>
        <button type="button" className="secondary" onClick={() => setAnchor(today())}>
          {t('agenda.today')}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setAnchor(addDays(anchor, byDay ? 1 : 7))}
        >
          →
        </button>

        {/* День называется днём недели и числом: диапазон из одной даты в
            обе стороны читался бы как ошибка */}
        <strong>
          {byDay ? longDate(period.start) : dateRange(period.start, period.end)}
        </strong>

        {/* Размах — тумблер, а не две кнопки: один орган на один вопрос, тот
            же, что «Мои · Вся школа» строкой выше */}
        {onSpan && (
          <Switch
            className="compact"
            label={t('agenda.span.label')}
            value={byDay ? 'day' : 'week'}
            options={[
              { value: 'week', label: t('agenda.span.week') },
              { value: 'day', label: t('agenda.span.day') },
            ]}
            onChange={onSpan}
          />
        )}

        <span className="year-picker">
          {years.map((year) => (
            <button
              type="button"
              key={year.id}
              className={year.id === yearId ? 'chip active' : 'chip'}
              onClick={() => {
                setYearId(year.id)
                setAnchor(clampToYear(anchor, year))
              }}
            >
              {year.name}
            </button>
          ))}
        </span>

        <button
          type="button"
          disabled={busy}
          onClick={() => setDialog({ type: 'copy' })}
        >
          {byDay ? t('agenda.copyDay') : t('agenda.copyWeek')}
        </button>
      </div>

      {/*
        Предмет → учитель → курс: не три условия, а одна цепочка.
        Правила сужения и доназначения — в `scheduleFilters.js`, здесь
        только три списка и одно состояние на них.
      */}
      <div className="class-filter">
        <label className="checkbox">
          {t('schoolSchedule.bySubject')}
          <select value={filters.subject} onChange={choose('subject')}>
            <option value="">{t('schoolSchedule.allSubjects')}</option>
            {options.subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </select>
        </label>

        <label className="checkbox">
          {t('schoolSchedule.byTeacher')}
          <select value={filters.teacher} onChange={choose('teacher')}>
            <option value="">{t('schoolSchedule.everyone')}</option>
            {options.teachers.map((member) => (
              <option key={member.id} value={member.id}>
                {[member.first_name, member.last_name].filter(Boolean).join(' ') ||
                  member.email}
              </option>
            ))}
          </select>
        </label>

        <label className="checkbox">
          {t('schoolSchedule.byCourse')}
          <select value={filters.course} onChange={choose('course')}>
            <option value="">{t('schoolSchedule.allCourses')}</option>
            {options.courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}

      {/*
        Две сетки, одна клетка: вид часа, его метки и подсказка считаются
        здесь и уезжают в обе. Разъехались бы они молча — в неделе час
        отменённый, в дне обычный, и оба вида про одно и то же расписание.
      */}
      {byDay ? (
        <DayGrid
          date={period.start}
          day={days[period.start] || {}}
          courses={columns}
          numbers={NUMBERS}
          busy={busy}
          lessonAt={lessonAt}
          renderLesson={(slot) => (
            <>
              {/* курс назван столбцом, номер — рядом, поэтому в клетке
                  остаётся то, чего по ним не видно: что прошло и почему
                  сорвалось. Повторять здесь имя курса значило бы написать
                  его десять раз в одном столбце */}
              <span className="cell-course">
                {slot.lesson_title ||
                  (slot.is_extra
                    ? t('schoolSchedule.day.extra')
                    : t('schoolSchedule.day.lesson'))}
              </span>
              {slot.is_cancelled && (
                <span className="cell-topic">
                  {slot.reason || t('schoolSchedule.day.cancelled')}
                </span>
              )}
            </>
          )}
          lessonClassName={cellClass}
          lessonTitle={cellTitle}
          onMenu={(date, slot, at) => setDialog({ type: 'menu', date, slot, at })}
          onAdd={(date, number, courseId) =>
            setDialog({ type: 'add', date, number, courseId })
          }
        />
      ) : (
      <WeekGrid
        dates={dates}
        days={days}
        numbers={NUMBERS}
        busy={busy}
        lessonsOn={lessonsOn}
        renderLesson={(slot) => (
          <>
            <span className="cell-course">{slot.course_name}</span>
            <span className="cell-topic">
              {slot.teacher_name || t('schoolSchedule.nobody')}
            </span>
          </>
        )}
        lessonClassName={cellClass}
        lessonTitle={cellTitle}
        /* любое нажатие — меню, и первым пунктом в нём «Открыть урок»:
           правая кнопка ничем себя не показывала, и половина работы с
           сеткой (отмена, перенос) просто не находилась */
        onMenu={(date, slot, at) => setDialog({ type: 'menu', date, slot, at })}
        onAdd={(date, number) => setDialog({ type: 'add', date, number })}
      />
      )}

      {/* оба нажатия названы словами: правая кнопка и долгое нажатие
          беззвучны — ниоткуда не видно, что они есть */}
      <p className="hint grid-hint">{t('agenda.gridHint')}</p>

      {/*
        Меню то же самое, что у учителя, и это главное здесь.
        Своё у администратора было куцым — открыть, удалить, удалить ряд, —
        и пометить час отменённым он не мог вовсе, хотя чужую неделю чинит
        именно он: сорвалось занятие, а сказать об этом нечем.

        Слот школьного ответа приводится к форме учительского: там `course`
        и `lesson`, тут ждут `course_id` и `recorded`. Одно поле переложить
        дешевле, чем держать второй компонент, который отстанет.
      */}
      {dialog?.type === 'menu' && (
        <LessonMenu
          lesson={{
            ...dialog.slot,
            course_id: dialog.slot.course,
            recorded: Boolean(dialog.slot.lesson),
          }}
          date={dialog.date}
          at={dialog.at}
          busy={busy}
          onCancel={(reason) => {
            setDialog(null)
            run(() => updateSlot(dialog.slot.id, { is_cancelled: true, reason }))
          }}
          onRestore={() => {
            setDialog(null)
            run(() => updateSlot(dialog.slot.id, { is_cancelled: false, reason: '' }))
          }}
          onMove={(fields) => {
            setDialog(null)
            run(() => moveSlot(dialog.slot.id, fields))
          }}
          onDelete={() => {
            setDialog(null)
            removeSlot(dialog.slot)
          }}
          onDeleteRow={() => {
            setDialog(null)
            removeRow(dialog.date, dialog.slot)
          }}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'add' && (
        <AddSchoolSlot
          date={dialog.date}
          number={dialog.number}
          courses={courses}
          /* в дневном виде столбец и есть курс: спрашивать о нём заново
             значит переспрашивать то, во что человек только что нажал */
          initialCourse={dialog.courseId ?? null}
          yearEnd={(years ?? []).find((year) => year.id === yearId)?.end_date}
          busy={busy}
          onSubmit={addSlot}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'copy' && (
        <CopyDialog
          source={period}
          slots={slots.map((slot) => ({
            ...slot,
            course_id: slot.course,
            is_extra: false,
            is_cancelled: false,
          }))}
          studyDates={new Set(Object.keys(days).filter((date) => days[date].is_study))}
          classes={courses}
          busy={busy}
          title={t('schoolSchedule.copyTitle')}
          note={t('schoolSchedule.copyNote')}
          onSubmit={({ target_start, target_end, mode, step }) =>
            run(
              () =>
                copySlots({
                  source_start: period.start,
                  source_end: period.end,
                  target_start,
                  target_end,
                  mode,
                  step,
                }),
              (result) =>
                t('schoolSchedule.copied', {
                  created: result.created,
                  skipped: result.skipped,
                }),
            )
          }
          onClose={() => setDialog(null)}
        />
      )}

    </main>
  )
}

/** Keep the shown week inside the chosen year, so the grid is never empty. */
function clampToYear(day, year) {
  if (day < year.start_date) return year.start_date
  if (day > year.end_date) return year.end_date
  return day
}

/**
 * Поставить урок в сетку школы: выбирается **курс**, и только он.
 *
 * Учителя тут не выбирают, потому что выбирать нечего: расписание
 * принадлежит курсу, а кто его ведёт — отдельное решение со своей строкой
 * (`CourseAssignment`) и своим местом в карточке курса. Пока у слота было
 * собственное поле учителя, эти два ответа могли разойтись: сетку рисовали
 * на одного, курс вёл другой.
 */
function AddSchoolSlot({
  date,
  number,
  courses,
  // курс, в столбец которого нажали (дневной вид); в недельном его нет —
  // там клетка это окно, а не курс
  initialCourse = null,
  yearEnd,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const [courseId, setCourseId] = useState(initialCourse ?? courses[0]?.id ?? null)
  // 0 — не повторять, 1 — каждую неделю, 2 — через неделю
  const [step, setStep] = useState(0)
  const [until, setUntil] = useState(yearEnd ?? '')

  const submit = (event) => {
    event.preventDefault()
    if (!courseId) return
    onSubmit({ course: courseId, ...(step ? { step, until } : {}) })
  }

  const chosen = courses.find((course) => course.id === courseId)
  const leads = (chosen?.teachers ?? []).map((teacher) => teacher.name).join(', ')

  return (
    <Modal onClose={onClose} title={t('schoolSchedule.addTitle', { number })}>
      <form onSubmit={submit}>

        <label>
          {t('school.courses.title')}
          <select
            autoFocus
            value={courseId ?? ''}
            disabled={busy}
            onChange={(event) => setCourseId(Number(event.target.value))}
          >
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>

        {/* кто ведёт — показываем, но не спрашиваем: это свойство курса */}
        <p className="hint">
          {t('schoolSchedule.leadIs', {
            name: leads || t('schoolSchedule.nobody'),
          })}
        </p>

        {/* сетку школы раскатывают рядами, и администратору это нужнее
            всех: ставить час на каждую неделю года по клетке — тридцать
            четыре нажатия вместо одного */}
        <RepeatChoice
          step={step}
          until={until}
          date={date}
          yearEnd={yearEnd}
          busy={busy}
          onStep={setStep}
          onUntil={setUntil}
        />

        <div className="actions">
          <button type="submit" disabled={busy || !courseId}>
            {t('common.add')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
