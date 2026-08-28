import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  LessonMenu,
  MoveModeMenu,
  MOVE_ONCE,
  MOVE_SERIES,
  moveBody,
  movesAsRow,
  RepeatChoice,
  RoomChoice,
} from './AgendaDialogs'
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
  fetchHomegroups,
  fetchRooms,
  fetchSchoolDay,
  fetchSchoolSlots,
  fetchScheduleSummary,
  fetchMembers,
  fetchSchoolYears,
  fetchYearDays,
  moveSlot,
  repeatSlot,
  setSlotRoom,
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
import {
  dayNumbers,
  describeMoveResult,
  describeRoomResult,
} from './scheduleLogic'
import { AXES, columns as axisColumns, layout, prefillFor } from './dayAxis'
import {
  courseMatches,
  emptyFilters,
  filterOptions,
  pick,
  reconcile,
  slotMatches,
} from './scheduleFilters'

/** Как зовут человека: имя с фамилией, а без них — почта. */
const personName = (member) =>
  [member.first_name, member.last_name].filter(Boolean).join(' ') || member.email

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
  axis = 'course',
  onAxis = null,
  onLoggedOut,
}) {
  const { t } = useTranslation()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [courses, setCourses] = useState([])
  const [members, setMembers] = useState([])
  const [rooms, setRooms] = useState([])
  const [homegroups, setHomegroups] = useState([])
  const [slots, setSlots] = useState([])
  const [lessonsPerDay, setLessonsPerDay] = useState(0)
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
    // кабинеты — справочник школы: короткий список, один запрос на заход.
    // Молча: школа, не заведшая ни одного, живёт как жила
    fetchRooms().then(setRooms).catch(() => setRooms([]))
    // длина школьного дня: столько рядов в обеих сетках. Молча, как кабинеты
    // рядом, — сетка без ответа рисуется по самим занятиям
    fetchSchoolDay()
      .then((answer) => setLessonsPerDay(answer.lessons_per_day))
      .catch(() => {})
    // классы года: столбцы дневного вида «по классам». Год важен — в
    // следующем 6А становится 7А, и это другая строка
    fetchHomegroups({ year: yearId })
      .then(setHomegroups)
      .catch(() => setHomegroups([]))
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

  // Ряды обеих сеток — школьный день, растянутый до самого позднего занятого
  // номера: сокращение дня уже стоящий час с экрана не убирает. Считается по
  // всем часам периода, а не по суженным: ряд, пропадающий от выбранного
  // фильтра, читался бы как правка расписания
  const numbers = useMemo(() => dayNumbers(lessonsPerDay, slots), [lessonsPerDay, slots])

  /*
   * Столбцы дневного вида и раскладка часов по ним — по выбранной оси.
   *
   * Считает это чистый модуль (`dayAxis.js`), и здесь остаётся только то,
   * чего он знать не может: какие курсы прошли сужение, кто из людей школы
   * ведёт хоть что-нибудь и какие кабинеты завела школа.
   *
   * Пустой столбец остаётся на любой оси: свободный кабинет — это и есть
   * ответ, ради которого на ось кабинетов смотрят, а курс без часов — место,
   * куда час ставят.
   */
  const columns = useMemo(
    () =>
      axisColumns(axis, {
        courses: courses.filter((course) => courseMatches(course, filters)),
        teachers: options.teachers.map((person) => ({
          id: person.id,
          name: personName(person),
        })),
        rooms,
        homegroups,
        slots: visible.filter((slot) => slot.date === period.start),
      }),
    [
      axis,
      courses,
      filters,
      options.teachers,
      rooms,
      homegroups,
      visible,
      period.start,
    ],
  )

  const byColumn = useMemo(
    () => layout(visible.filter((slot) => slot.date === period.start), axis),
    [visible, period.start, axis],
  )

  /*
   * Часы столбца на этом номере — списком: клетка держит стопку.
   *
   * На оси курсов их не бывает больше одного (`unique_together`), а на
   * остальных бывает: делимый зал вмещает два занятия, у заменяющего
   * учителя два часа в одном номере — законное состояние. Сетка, умеющая
   * показать один, молча прятала бы второй.
   */
  const lessonsIn = (key, number) => byColumn.get(key)?.get(number) ?? []

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
    (slot.debt ? ' debt' : '') +
    // кабинет делится с чужим часом. Метка на клетке, а не в строке с
    // названием кабинета: показ кабинетов человек выключает, а
    // предупреждение — не украшение строки, а сообщение
    (busyRoom(slot) ? ' room-clash' : '') +
    // а это уже про людей: кто-то из учеников стоит в это же время ещё
    // где-то. Две подгруппы в одном часу — норма, тот же человек в обеих —
    // нет, и различить это может только сервер, знающий составы
    (busyStudents(slot).length ? ' student-clash' : '')

  /**
   * Что написано в клетке дня — зависит от оси.
   *
   * Правило одно: в клетке лежит то, чего **не видно по столбцу и ряду**.
   * Номер известен рядом, а дальше по-разному: на оси курсов курс назван
   * столбцом, и остаётся тема; на оси кабинетов и учителей курс как раз и
   * есть то, чего по столбцу не видно, и без него клетка была бы набором
   * одинаковых зелёных квадратов.
   */
  const dayCell = (slot) => (
    <>
      <span className="cell-course">
        {axis === 'course'
          ? slot.lesson_title ||
            (slot.is_extra
              ? t('schoolSchedule.day.extra')
              : t('schoolSchedule.day.lesson'))
          : slot.course_name}
      </span>
      {(axis === 'room' || axis === 'homegroup') && slot.teacher_name && (
        <span className="cell-topic">{slot.teacher_name}</span>
      )}
      {axis === 'teacher' && slot.room_name && (
        <span className="cell-topic">{slot.room_name}</span>
      )}
      {slot.is_cancelled && (
        <span className="cell-topic">
          {slot.reason || t('schoolSchedule.day.cancelled')}
        </span>
      )}
      {axis === 'course' && slot.room_name && (
        <span className="cell-room">{slot.room_name}</span>
      )}
    </>
  )

  const cellTitle = (slot) => {
    const clash = busyStudents(slot)

    return [
      slot.course_name,
      slot.teacher_name,
      slot.room_name,
      slot.lesson_title,
      // имена прямо в подсказке: «кто-то пересекается» — сообщение, с
      // которым нечего делать, а починить расписание можно, только зная кто
      clash.length ? t('warnings.slot_student_busy_short', { names: clash.join(', ') }) : '',
    ]
      .filter(Boolean)
      .join(' — ')
  }

  /*
   * Делит ли час кабинет — считает сервер и говорит предупреждением.
   *
   * Своего расчёта у экрана нет и быть не должно: делимый зал молчит, а
   * отменённый час кабинет освобождает — два правила, которые второй раз
   * записанные разъехались бы с первым. Здесь только чтение кода.
   */
  const busyRoom = (slot) =>
    (slot.warnings ?? []).some((one) => one.code === 'slot_room_busy')

  /** Кто из учеников этого часа стоит в это же время ещё где-то. */
  const busyStudents = (slot) =>
    (slot.warnings ?? []).find((one) => one.code === 'slot_student_busy')?.params
      ?.students ?? []

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
   * Перенос: один запрос на оба режима, отчёт — только у постоянного.
   *
   * Разовый рисуется сам собой: отмена здесь, дополнительное занятие там, и
   * обе записи видны в сетке. Постоянный двигает ряд до конца года, часть
   * которого могла упереться в занятый номер или каникулы, — и молчание
   * читалось бы как «переехало всё».
   */
  const runMove = (slot, fields) =>
    run(
      () => moveSlot(slot.id, fields),
      fields.mode === MOVE_SERIES ? (result) => describeMoveResult(result, t) : undefined,
    )

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

        {/* Ось столбцов — вопрос только дневного вида: в неделе столбцы это
            дни, и выбирать там нечего. Поэтому тумблера в недельном виде
            нет вовсе, а не стоит выключенным */}
        {byDay && onAxis && (
          <Switch
            className="compact"
            label={t('agenda.axis.label')}
            value={axis}
            options={AXES.map((one) => ({
              value: one,
              label: t(`agenda.axis.${one}`),
            }))}
            onChange={onAxis}
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
                {personName(member)}
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
          columns={columns}
          numbers={numbers}
          busy={busy}
          lessonsIn={lessonsIn}
          renderLesson={dayCell}
          lessonClassName={cellClass}
          lessonTitle={cellTitle}
          onMenu={(date, slot, at) => setDialog({ type: 'menu', date, slot, at })}
          onAdd={(date, number, column) =>
            setDialog({ type: 'add', date, number, ...prefillFor(axis, column) })
          }
        />
      ) : (
      <WeekGrid
        dates={dates}
        days={days}
        numbers={numbers}
        busy={busy}
        lessonsOn={lessonsOn}
        renderLesson={(slot) => (
          <>
            <span className="cell-course">{slot.course_name}</span>
            <span className="cell-topic">
              {slot.teacher_name || t('schoolSchedule.nobody')}
            </span>
            {slot.room_name && <span className="cell-room">{slot.room_name}</span>}
          </>
        )}
        lessonClassName={cellClass}
        lessonTitle={cellTitle}
        /* любое нажатие — меню, и первым пунктом в нём «Открыть урок»:
           правая кнопка ничем себя не показывала, и половина работы с
           сеткой (отмена, перенос) просто не находилась */
        onMenu={(date, slot, at) => setDialog({ type: 'menu', date, slot, at })}
        onAdd={(date, number) => setDialog({ type: 'add', date, number })}
        /* Тот же перенос, что пункт «Перенести» в меню: один `moveSlot`, одна
           причина отмены по умолчанию. Неделя школы — та же сетка, что у
           учителя, и час в ней принадлежит курсу, а не столбцу, поэтому жест
           здесь значит ровно то же, что там. (В дневном виде его нет, и это
           отдельное решение: соседний столбец там — другой курс.)

           Отменённое не тащим — час уже свободен, и «перенос отмены» ничего
           не значит.

           Чем перенос будет — разовым срывом или новым расписанием, — жест
           не знает, и спрашивается это там же, где отпустили. У часа без
           ряда (записанный, дополнительный) выбора нет, и он едет сразу. */
        onDrop={(slot, from, target, at) => {
          if (slot.is_cancelled) return
          if (!movesAsRow({ ...slot, recorded: Boolean(slot.lesson) })) {
            return runMove(slot, moveBody(target, MOVE_ONCE, t))
          }
          setDialog({ type: 'moveMode', slot, target, at })
        }}
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
            runMove(dialog.slot, fields)
          }}
          /* причина уходит вместе с флагом — тем же движением, что «Вернуть»
             стирает причину отмены: у неотменённого часа она объясняет
             ровно то, что мы сейчас снимаем */
          onRegular={() => {
            setDialog(null)
            run(() => updateSlot(dialog.slot.id, { is_extra: false, reason: '' }))
          }}
          rooms={rooms}
          onRoom={(room, scope) => {
            setDialog(null)
            // ряд отвечает числами, одиночный час — самим часом: сколько
            // часов ряда несут запись и потому останутся при своём кабинете,
            // знает только сервер
            run(
              () => setSlotRoom(dialog.slot.id, { room, mode: scope }),
              scope === MOVE_SERIES
                ? (result) => describeRoomResult(result, t)
                : undefined,
            )
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

      {/* бросок состоялся, и остался один вопрос: разовый это перенос или
          новое расписание. Закрыть, не ответив, значит не переносить вовсе */}
      {dialog?.type === 'moveMode' && (
        <MoveModeMenu
          at={dialog.at}
          target={dialog.target}
          busy={busy}
          onPick={(mode) => runMove(dialog.slot, moveBody(dialog.target, mode, t))}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'add' && (
        <AddSchoolSlot
          date={dialog.date}
          number={dialog.number}
          courses={courses}
          rooms={rooms}
          /* в дневном виде столбец и есть курс: спрашивать о нём заново
             значит переспрашивать то, во что человек только что нажал */
          initialCourse={dialog.course ?? null}
          initialRoom={dialog.room ?? null}
          /* столбец учителя сужает список курсов, а не заменяет вопрос:
             час принадлежит курсу, и без него его не создать */
          onlyTeacher={dialog.teacher ?? null}
          onlyHomegroup={dialog.homegroup ?? null}
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
  rooms = [],
  // курс, в столбец которого нажали (дневной вид); в недельном его нет —
  // там клетка это окно, а не курс
  initialCourse = null,
  // кабинет столбца — на оси кабинетов он уже известен
  initialRoom = null,
  // учитель столбца: не подставляется никуда (учителя у часа нет, есть у
  // курса), а **сужает** список курсов до его собственных
  onlyTeacher = null,
  // класс столбца: сужает так же — до курсов, где учатся его ученики
  onlyHomegroup = null,
  yearEnd,
  busy,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const shown = courses
    .filter(
      (course) =>
        !onlyTeacher ||
        (course.teachers ?? []).some((one) => one.id === onlyTeacher),
    )
    .filter(
      (course) => !onlyHomegroup || (course.homegroups ?? []).includes(onlyHomegroup),
    )
  const [courseId, setCourseId] = useState(initialCourse ?? shown[0]?.id ?? null)
  const [room, setRoom] = useState(initialRoom)
  // 0 — не повторять, 1 — каждую неделю, 2 — через неделю
  const [step, setStep] = useState(0)
  const [until, setUntil] = useState(yearEnd ?? '')

  const submit = (event) => {
    event.preventDefault()
    if (!courseId) return
    onSubmit({ course: courseId, room, ...(step ? { step, until } : {}) })
  }

  const chosen = shown.find((course) => course.id === courseId)
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
            {shown.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>

        <RoomChoice rooms={rooms} value={room} busy={busy} onChange={setRoom} />

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
