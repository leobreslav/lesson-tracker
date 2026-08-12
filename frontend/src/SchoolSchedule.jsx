import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ClearDialog from './ClearDialog'
import CopyDialog from './CopyDialog'
import EmptyState from './EmptyState'
import Modal from './Modal'
import WeekGrid from './WeekGrid'
import {
  clearMasterSlots,
  copyMasterSlots,
  createMasterSlot,
  deleteMasterSlot,
  fetchCourses,
  fetchMasterSlots,
  fetchMasterSummary,
  fetchMembers,
  fetchSchoolYears,
  fetchYearDays,
} from './api'
import {
  addDays,
  eachDate,
  endOfWeek,
  startOfWeek,
  today,
} from './calendarLogic'
import { dateRange, firstWeekday } from './dates'
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
  const [anchor, setAnchor] = useState(today)
  const [teacherFilter, setTeacherFilter] = useState('')
  const [courseFilter, setCourseFilter] = useState('')
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
    fetchCourses(yearId).then(setCourses).catch(handleError)
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
      fetchMasterSlots({ year: yearId, start: period.start, end: period.end }),
      fetchMasterSummary({ year: yearId }),
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

  const addSlot = (fields) =>
    run(() =>
      createMasterSlot({
        year: yearId,
        date: dialog.date,
        lesson_number: dialog.number,
        ...fields,
      }),
    )

  const removeSlot = (slot) => {
    if (!window.confirm(t('schoolSchedule.deleteConfirm', { name: slot.course_name })))
      return
    run(() => deleteMasterSlot(slot.id))
  }

  if (years === null) {
    return (
      <main className="page">
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
    <main className="page">
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
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => setDialog({ type: 'clear' })}
        >
          {t('agenda.clearPeriod')}
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
            {slot.course_name}
            <span className="cell-topic">
              {slot.teacher_name || t('schoolSchedule.nobody')}
            </span>
          </>
        )}
        lessonClassName={(slot) =>
          slot.teacher ? 'cell lesson' : 'cell lesson unassigned'
        }
        onOpen={(date, slot) => removeSlot(slot)}
        onAdd={(date, number) => setDialog({ type: 'add', date, number })}
      />

      {dialog?.type === 'add' && (
        <AddMasterSlot
          date={dialog.date}
          number={dialog.number}
          courses={courses}
          members={members}
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
          onSubmit={({ target_start, target_end, mode }) =>
            run(
              () =>
                copyMasterSlots({
                  source_start: period.start,
                  source_end: period.end,
                  target_start,
                  target_end,
                  mode,
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

      {dialog?.type === 'clear' && (
        <ClearDialog
          range={period}
          slots={slots.map((slot) => ({ ...slot, course_id: slot.course }))}
          classes={courses}
          busy={busy}
          onSubmit={({ classIds }) =>
            run(
              async () => {
                let deleted = 0
                for (const courseId of classIds) {
                  const part = await clearMasterSlots({ ...period, courseId })
                  deleted += part.deleted
                }
                return { deleted }
              },
              (result) => t('agenda.cleared', { count: result.deleted }),
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

/** Who teaches what at this hour — the one thing an administrator adds. */
function AddMasterSlot({ date, number, courses, members, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [courseId, setCourseId] = useState(courses[0]?.id ?? null)
  const [teacherId, setTeacherId] = useState('')

  const submit = (event) => {
    event.preventDefault()
    if (!courseId) return
    onSubmit({ course: courseId, teacher: teacherId || null })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{t('schoolSchedule.addTitle', { number })}</h3>

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

        <label>
          {t('schoolSchedule.teacher')}
          <select
            value={teacherId}
            disabled={busy}
            onChange={(event) => setTeacherId(event.target.value)}
          >
            <option value="">{t('schoolSchedule.nobody')}</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {[member.first_name, member.last_name].filter(Boolean).join(' ') ||
                  member.email}
              </option>
            ))}
          </select>
        </label>

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
