import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LessonMenu, RepeatChoice } from './AgendaDialogs'
import CopyDialog from './CopyDialog'
import EmptyState from './EmptyState'
import Modal from './Modal'
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
import { dateRange, firstWeekday } from './dates'
import { weekdayIndex } from './weekStart'
import { useKept } from './remember'
import { MAX_LESSON_NUMBER } from './scheduleLogic'

const NUMBERS = Array.from({ length: MAX_LESSON_NUMBER }, (_, index) => index + 1)

/**
 * The school-wide timetable, kept by administrators.
 *
 * The same week grid as «My schedule» — one component, so the two screens
 * cannot drift apart — with the teacher's name in the cell instead of the
 * topic, and filters that a personal schedule has no use for.
 */
export default function SchoolSchedule({ onLoggedOut }) {
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
  const [teacherFilter, setTeacherFilter] = useKept('school.schedule.teacher', '')
  const [courseFilter, setCourseFilter] = useKept('school.schedule.course', '')
  const [dialog, setDialog] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const weekStart = firstWeekday()
  const period = useMemo(
    () => ({ start: startOfWeek(anchor, weekStart), end: endOfWeek(anchor, weekStart) }),
    [anchor, weekStart],
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

  const visible = useMemo(
    () =>
      slots.filter(
        (slot) =>
          (!teacherFilter || String(slot.teacher) === teacherFilter) &&
          (!courseFilter || String(slot.course) === courseFilter),
      ),
    [slots, teacherFilter, courseFilter],
  )

  const lessonsOn = (date) => visible.filter((slot) => slot.date === date)

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
        <button type="button" className="secondary" onClick={() => setAnchor(addDays(anchor, -7))}>
          ←
        </button>
        <button type="button" className="secondary" onClick={() => setAnchor(today())}>
          {t('agenda.today')}
        </button>
        <button type="button" className="secondary" onClick={() => setAnchor(addDays(anchor, 7))}>
          →
        </button>

        <strong>{dateRange(period.start, period.end)}</strong>

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
          {t('agenda.copyWeek')}
        </button>
      </div>

      <div className="class-filter">
        <label className="checkbox">
          {t('schoolSchedule.byTeacher')}
          <select
            value={teacherFilter}
            onChange={(event) => setTeacherFilter(event.target.value)}
          >
            <option value="">{t('schoolSchedule.everyone')}</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {[member.first_name, member.last_name].filter(Boolean).join(' ') ||
                  member.email}
              </option>
            ))}
          </select>
        </label>

        <label className="checkbox">
          {t('schoolSchedule.byCourse')}
          <select
            value={courseFilter}
            onChange={(event) => setCourseFilter(event.target.value)}
          >
            <option value="">{t('schoolSchedule.allCourses')}</option>
            {courses.map((course) => (
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
        lessonClassName={(slot) =>
          (slot.teacher ? 'cell lesson' : 'cell lesson unassigned') +
          // отменённый и дополнительный час выглядят тут так же, как у
          // учителя. Не выглядели вовсе: отменить из этой сетки было
          // нечем, и никто не замечал, что перечёркнутых часов она не
          // рисует — то есть администратор видел сорванное занятие как
          // обычное
          (slot.is_cancelled ? ' cancelled' : '') +
          (slot.is_extra ? ' extra' : '') +
          // те же метки, что у учителя: записанный час — галочка,
          // прошедший без записи — красная точка. Администратор смотрит
          // на то же расписание, и метки на нём должны значить то же
          (slot.lesson ? ' recorded' : '') +
          (slot.debt ? ' debt' : '')
        }
        lessonTitle={(slot) =>
          [slot.course_name, slot.teacher_name].filter(Boolean).join(' — ')
        }
        /* любое нажатие — меню, и первым пунктом в нём «Открыть урок»:
           правая кнопка ничем себя не показывала, и половина работы с
           сеткой (отмена, перенос) просто не находилась */
        onMenu={(date, slot, at) => setDialog({ type: 'menu', date, slot, at })}
        onAdd={(date, number) => setDialog({ type: 'add', date, number })}
      />

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
function AddSchoolSlot({ date, number, courses, yearEnd, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [courseId, setCourseId] = useState(courses[0]?.id ?? null)
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
