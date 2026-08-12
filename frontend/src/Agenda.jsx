import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { AddLessonDialog, LessonMenu } from './AgendaDialogs'
import ClearDialog from './ClearDialog'
import EmptyState from './EmptyState'
import CopyDialog from './CopyDialog'
import {
  clearSlots,
  copySlots,
  fetchLayoutAgenda,
  createSlot,
  deleteSlot,
  fetchAgenda,
  fetchClasses,
  fetchSchoolYears,
  updateSlot,
} from './api'
import {
  addDays,
  eachDate,
  endOfMonth,
  endOfWeek,
  formatDate,
  daysBetween,
  groupByMonth,
  parseDate,
  startOfMonth,
  startOfWeek,
  today,
  weekdayOf,
} from './calendarLogic'
import {
  dateRange,
  firstWeekday,
  monthTitle,
  shortWeekday,
  weekdayHeadings,
} from './dates'
import { MAX_LESSON_NUMBER, describeCopyResult } from './scheduleLogic'

const NUMBERS = Array.from({ length: MAX_LESSON_NUMBER }, (_, index) => index + 1)

const EMPTY = { lessons: {}, days: {} }

// the "lesson topics" checkbox survives a reload: this is an ordinary web
// application, localStorage fits here and costs nothing
const TOPICS_KEY = 'agendaShowTopics'

function readTopicsFlag() {
  try {
    return localStorage.getItem(TOPICS_KEY) === '1'
  } catch {
    return false
  }
}

function saveTopicsFlag(value) {
  try {
    localStorage.setItem(TOPICS_KEY, value ? '1' : '0')
  } catch {
    // private mode — we simply do not remember
  }
}

/** Lessons from the agenda answer as a flat list, each carrying its date. */
function flatten(lessons) {
  return Object.entries(lessons).flatMap(([date, list]) =>
    list.map((item) => ({ ...item, date })),
  )
}

function studyDatesOf(days) {
  return Object.entries(days)
    .filter(([, day]) => day.is_study)
    .map(([date]) => date)
}

function shiftMonth(iso, step) {
  const date = parseDate(iso)
  return formatDate(new Date(date.getFullYear(), date.getMonth() + step, 1, 12))
}

function lessonClassName(lesson) {
  return (
    'cell lesson' +
    (lesson.is_cancelled ? ' cancelled' : '') +
    (lesson.is_extra ? ' extra' : '')
  )
}

export default function Agenda({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [anchor, setAnchor] = useState(today)
  const [mode, setMode] = useState('week')
  const [data, setData] = useState(EMPTY)
  const [years, setYears] = useState([])
  const [classes, setClasses] = useState([])
  const [hidden, setHidden] = useState(() => new Set())

  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [dialog, setDialog] = useState(null) // {type:'add'|'lesson'|'copy'|'clear', ...}
  // what already sits in the target period — purely for an exact preview
  const [targetPeriod, setTargetPeriod] = useState(EMPTY)
  // days selected in the grid: {start, end}; Shift+click drags a range
  const [selection, setSelection] = useState(null)
  // plan topics per lesson: slot_id → {title, section_title};
  // null means not loaded yet, so "no topic" is not printed for nothing
  const [topics, setTopics] = useState(null)
  const [showTopics, setShowTopics] = useState(readTopicsFlag)

  const tempId = useRef(0)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  // the week runs from the language's first weekday: Monday in Russian,
  // Sunday in American English
  const weekStart = firstWeekday()
  const period = useMemo(
    () =>
      mode === 'week'
        ? { start: startOfWeek(anchor, weekStart), end: endOfWeek(anchor, weekStart) }
        : { start: startOfMonth(anchor), end: endOfMonth(anchor) },
    [anchor, mode, weekStart],
  )

  useEffect(() => {
    let cancelled = false

    Promise.all([fetchSchoolYears(), fetchClasses()])
      .then(([yearList, classList]) => {
        if (cancelled) return
        setYears(yearList)
        setClasses(classList)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  const load = useCallback(
    () => fetchAgenda(period.start, period.end).then(setData),
    [period],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    load()
      .catch((err) => {
        if (!cancelled) handleError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [load, handleError])

  // topics are fetched only while shown: otherwise every week costs a request
  useEffect(() => {
    if (!showTopics) {
      setTopics(null)
      return undefined
    }

    let cancelled = false
    fetchLayoutAgenda(period.start, period.end)
      .then((payload) => {
        if (!cancelled) setTopics(payload.slots)
      })
      .catch(() => {
        // silently: a topic is a bonus, the grid must not break over it
        if (!cancelled) setTopics(null)
      })

    return () => {
      cancelled = true
    }
    // data is in the deps on purpose: editing a lesson shifts the topics
  }, [showTopics, period, data])

  const toggleTopics = (value) => {
    setShowTopics(value)
    saveTopicsFlag(value)
  }

  const dates = useMemo(
    () => eachDate(period.start, period.end),
    [period],
  )

  const yearById = useMemo(
    () => new Map(years.map((year) => [year.id, year])),
    [years],
  )

  /** Classes whose school year covers this date — only they can be placed. */
  const classesFor = useCallback(
    (date) =>
      classes.filter((item) => {
        const year = yearById.get(item.year)
        return year && year.start_date <= date && date <= year.end_date
      }),
    [classes, yearById],
  )

  /**
   * Who this lesson can be given to.
   *
   * A class that already has something on this number is dropped: even a
   * cancelled lesson occupies the (class, number) pair in unique_together.
   * Another class is not blocked by that cancellation — the slot is free.
   */
  const freeClassesFor = useCallback(
    (date, number) => {
      const busyClasses = new Set(
        (data.lessons[date] || [])
          .filter((item) => item.lesson_number === number)
          .map((item) => item.class_id),
      )
      return classesFor(date).filter((item) => !busyClasses.has(item.id))
    },
    [data, classesFor],
  )

  const visibleClasses = useMemo(
    () =>
      classes.filter((item) => {
        const year = yearById.get(item.year)
        return year && year.start_date <= period.end && period.start <= year.end_date
      }),
    [classes, yearById, period],
  )

  const lessonsOn = useCallback(
    (date) => (data.lessons[date] || []).filter((item) => !hidden.has(item.class_id)),
    [data, hidden],
  )

  const summary = useMemo(() => {
    const visible = dates.flatMap((date) => lessonsOn(date))
    const live = visible.filter((item) => !item.is_cancelled)
    const byClass = {}
    live.forEach((item) => {
      byClass[item.class_name] = (byClass[item.class_name] || 0) + 1
    })

    return { total: live.length, cancelled: visible.length - live.length, byClass }
  }, [dates, lessonsOn])

  /** An optimistic edit: draw at once, restore the old answer on failure. */
  const mutate = useCallback(
    async (lessons, request) => {
      const snapshot = data
      setError(null)
      setBusy(true)
      setData({ ...data, lessons })

      try {
        await request()
        await load()
      } catch (err) {
        setData(snapshot)
        handleError(err)
      } finally {
        setBusy(false)
      }
    },
    [data, load, handleError],
  )

  const handleAdd = ({ school_class, is_extra, reason }) => {
    const { date, number } = dialog
    setDialog(null)
    tempId.current -= 1

    const optimistic = {
      id: tempId.current,
      lesson_number: number,
      class_id: school_class,
      class_name: classes.find((item) => item.id === school_class)?.name ?? '',
      is_cancelled: false,
      is_extra,
      reason,
    }

    return mutate(
      {
        ...data.lessons,
        [date]: [...(data.lessons[date] || []), optimistic].sort(
          (a, b) => a.lesson_number - b.lesson_number,
        ),
      },
      () =>
        createSlot({
          school_class,
          date,
          lesson_number: number,
          is_extra,
          reason,
        }),
    )
  }

  const patchLesson = (date, lesson, fields) => {
    setDialog(null)
    return mutate(
      {
        ...data.lessons,
        [date]: data.lessons[date].map((item) =>
          item.id === lesson.id ? { ...item, ...fields } : item,
        ),
      },
      () => updateSlot(lesson.id, fields),
    )
  }

  const removeLesson = (date, lesson) => {
    setDialog(null)
    return mutate(
      {
        ...data.lessons,
        [date]: data.lessons[date].filter((item) => item.id !== lesson.id),
      },
      () => deleteSlot(lesson.id),
    )
  }

  /** Load the target period so the preview knows which numbers are taken. */
  const loadTarget = useCallback(
    ({ start, end }) => {
      if (!start || !end || end < start) return

      fetchAgenda(start, end)
        .then(setTargetPeriod)
        .catch(() => setTargetPeriod(EMPTY))
    },
    [],
  )

  const copySource = useMemo(() => {
    // the source is the whole shown period across every class: the display
    // filter does not affect copying, cancelled and extra lessons stay put
    const seen = new Set()
    const merged = []

    for (const lesson of [...flatten(data.lessons), ...flatten(targetPeriod.lessons)]) {
      if (seen.has(lesson.id)) continue
      seen.add(lesson.id)
      merged.push(lesson)
    }

    return {
      slots: merged,
      studyDates: new Set([
        ...studyDatesOf(data.days),
        ...studyDatesOf(targetPeriod.days),
      ]),
    }
  }, [data, targetPeriod])

  /** A bulk operation: run it, re-read the period, report. */
  const runBulk = async (request, describe) => {
    setDialog(null)
    setBusy(true)
    setError(null)
    setNotice(null)

    try {
      const result = await request()
      await load()
      setNotice(describe(result))
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  /** Copying: every class in one request, a subset one request per class. */
  const handleCopy = ({ target_start, target_end, mode, classIds }) => {
    const source = copyRange
    const everyClass = classIds.length === visibleClasses.length

    return runBulk(async () => {
      const common = {
        source_start: source.start,
        source_end: source.end,
        target_start,
        target_end,
        mode,
      }

      if (everyClass) return copySlots(common)

      const totals = { created: 0, skipped: 0, deleted: 0, conflicts: [] }
      for (const classId of classIds) {
        const part = await copySlots({ ...common, class_id: classId })
        totals.created += part.created
        totals.skipped += part.skipped
        totals.deleted += part.deleted
        totals.conflicts.push(...part.conflicts)
      }
      return totals
    }, (result) => describeCopyResult(result, t))
  }

  /** Clearing: the endpoint takes one class, so one request per class. */
  const handleClear = ({ only_regular, classIds }) => {
    const range = selection

    return runBulk(
      async () => {
        let deleted = 0
        for (const classId of classIds) {
          const part = await clearSlots({
            classId,
            start: range.start,
            end: range.end,
            onlyRegular: only_regular,
          })
          deleted += part.deleted
        }
        return { deleted }
      },
      (result) => t('agenda.cleared', { count: result.deleted }),
    )
  }

  const toggleClass = (id) =>
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const step = (direction) =>
    setAnchor((current) =>
      mode === 'week' ? addDays(current, 7 * direction) : shiftMonth(current, direction),
    )

  /** A click on a day heading selects it, Shift+click drags a range. */
  const pickDay = (date, event) => {
    setNotice(null)
    setSelection((current) => {
      if (!event.shiftKey || !current) return { start: date, end: date }
      const bounds = [current.start, date].sort()
      return { start: bounds[0], end: bounds[1] }
    })
  }

  const inSelection = (date) =>
    selection && selection.start <= date && date <= selection.end

  const selectedDays = selection
    ? daysBetween(selection.start, selection.end) + 1
    : 0

  // with nothing selected we copy the whole shown period
  const copyRange = selection ?? { start: period.start, end: period.end }

  /**
   * The lesson topic from the plan.
   *
   * Nothing is drawn until the topics load. Once they have, and no plan
   * lesson reached this slot (there are more slots than lessons), we say so
   * plainly: otherwise "no topic" and "not shown" look the same.
   */
  const topicOf = (lesson) => {
    if (!showTopics || !topics) return null

    const topic = topics[lesson.id]
    if (!topic) {
      return <span className="cell-topic missing">{t('agenda.noTopic')}</span>
    }

    return (
      <span className="cell-topic" title={topic.title}>
        {topic.title}
      </span>
    )
  }

  const openLesson = (date, lesson) => setDialog({ type: 'lesson', date, lesson })

  const openFreeCell = (date, number) => {
    if (!data.days[date]?.is_study) return
    setDialog({ type: 'add', date, number })
  }

  const dayHeadClass = (date) => {
    const day = data.days[date] || {}
    return (
      'day-head' +
      (day.is_study ? '' : ' locked') +
      (date === today() ? ' today' : '') +
      (inSelection(date) ? ' selected' : '')
    )
  }

  const renderWeek = () => (
    <div
      className="week-grid"
      style={{ gridTemplateColumns: `2.5rem repeat(${dates.length}, minmax(0, 1fr))` }}
    >
      <div className="corner" />
      {dates.map((date) => {
        const day = data.days[date] || {}
        return (
          <button
            type="button"
            key={date}
            className={dayHeadClass(date)}
            title={t('agenda.selectHint', {
              title: day.title || t('agenda.selectDay'),
            })}
            onClick={(event) => pickDay(date, event)}
          >
            <span>{shortWeekday(date)}</span>
            <strong>{parseDate(date).getDate()}</strong>
            {!day.is_study && <em>{day.title || t('agenda.notStudy')}</em>}
          </button>
        )
      })}

      {NUMBERS.map((number) => (
        <Fragment key={number}>
          <div className="row-head">{number}</div>
          {dates.map((date) => {
            // a cancelled lesson frees the slot without leaving the screen:
            // a cell can hold both the cancellation and its replacement
            const inCell = lessonsOn(date)
              .filter((item) => item.lesson_number === number)
              .sort((a, b) => Number(a.is_cancelled) - Number(b.is_cancelled))
            const taken = inCell.some((item) => !item.is_cancelled)
            const locked = !data.days[date]?.is_study

            if (!inCell.length && locked) {
              return <div key={date} className="cell locked" />
            }

            const addButton = (
              <button
                type="button"
                className={inCell.length ? 'cell free add-more' : 'cell free'}
                aria-label={t('agenda.addLesson', { number })}
                disabled={busy}
                onClick={() => openFreeCell(date, number)}
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
                    className={lessonClassName(lesson)}
                    title={lesson.reason || undefined}
                    disabled={busy}
                    onClick={() => openLesson(date, lesson)}
                  >
                    {lesson.class_name}
                    {topicOf(lesson)}
                  </button>
                ))}
                {/* the slot is free: only cancellations are left */}
                {!taken && !locked && addButton}
              </div>
            )
          })}
        </Fragment>
      ))}
    </div>
  )

  const renderMonth = () => {
    const grid = dates.map((date) => ({
      date,
      weekday: weekdayOf(date),
      ...(data.days[date] || {}),
    }))

    return (
      <div className="months agenda-months">
        {groupByMonth(grid, firstWeekday()).map((month) => (
          <section className="month" key={month.key}>
            <h3>{monthTitle(month.first)}</h3>
            <div className="month-grid">
              {weekdayHeadings().map((heading) => (
                <div className="weekday" key={heading.weekday}>
                  {heading.label}
                </div>
              ))}
              {Array.from({ length: month.leading }, (_, index) => (
                <div className="day blank" key={`blank-${index}`} />
              ))}
              {month.days.map((day) => (
                <div
                  key={day.date}
                  className={
                    `day agenda-day ${day.status || 'outside'}` +
                    (day.is_study ? '' : ' locked') +
                    (day.date === today() ? ' today' : '')
                  }
                  title={day.title || undefined}
                >
                  <button
                    type="button"
                    className="link date"
                    title={t('agenda.openWeek')}
                    onClick={() => {
                      setAnchor(day.date)
                      setMode('week')
                    }}
                  >
                    {parseDate(day.date).getDate()}
                  </button>
                  {lessonsOn(day.date).map((lesson) => (
                    <button
                      type="button"
                      key={lesson.id}
                      className={lessonClassName(lesson)}
                      title={lesson.reason || undefined}
                      disabled={busy}
                      onClick={() => openLesson(day.date, lesson)}
                    >
                      <span className="slot">{lesson.lesson_number}</span>{' '}
                      {lesson.class_name}
                      {topicOf(lesson)}
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('agenda.title')}</h1>
      </header>

      <div className="agenda-bar">
        <button type="button" className="secondary" onClick={() => step(-1)}>
          ←
        </button>
        <button type="button" className="secondary" onClick={() => setAnchor(today())}>
          {t('agenda.today')}
        </button>
        <button type="button" className="secondary" onClick={() => step(1)}>
          →
        </button>

        <strong>{dateRange(period.start, period.end)}</strong>

        <input
          type="date"
          value={anchor}
          aria-label={t('agenda.goToDate')}
          onChange={(event) => event.target.value && setAnchor(event.target.value)}
        />

        <span className="year-picker">
          <button
            type="button"
            className={mode === 'week' ? 'chip active' : 'chip'}
            onClick={() => setMode('week')}
          >
            {t('agenda.week')}
          </button>
          <button
            type="button"
            className={mode === 'month' ? 'chip active' : 'chip'}
            onClick={() => setMode('month')}
          >
            {t('agenda.month')}
          </button>
        </span>

        <button
          type="button"
          disabled={busy || loading || !!selection}
          title={selection ? t('agenda.clearSelectionFirst') : undefined}
          onClick={() => {
            setTargetPeriod(EMPTY)
            setDialog({ type: 'copy' })
          }}
        >
          {t(mode === 'week' ? 'agenda.copyWeek' : 'agenda.copyMonth')}
        </button>
      </div>

      {selection && (
        <div className="selection-bar">
          <span>
            {t('agenda.selected', {
              days: t('common.dayCount', { count: selectedDays }),
              range: dateRange(selection.start, selection.end),
            })}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setTargetPeriod(EMPTY)
              setDialog({ type: 'copy' })
            }}
          >
            {t('agenda.copyToPeriod')}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => setDialog({ type: 'clear' })}
          >
            {t('agenda.clearPeriod')}
          </button>
          <button
            type="button"
            className="link"
            aria-label={t('common.cancel')}
            onClick={() => setSelection(null)}
          >
            ✕
          </button>
        </div>
      )}

      {!loading && !visibleClasses.length && (
        <EmptyState
          title={t('agenda.empty.title')}
          actions={
            <button type="button" onClick={() => navigate('/classes')}>
              {t('agenda.empty.action')}
            </button>
          }
        >
          {t('agenda.empty.hint')}
        </EmptyState>
      )}

      {visibleClasses.length > 0 && (
        <div className="class-filter">
          <span className="hint">{t('agenda.show')}</span>
          {visibleClasses.map((item) => (
            <label key={item.id} className="checkbox">
              <input
                type="checkbox"
                checked={!hidden.has(item.id)}
                onChange={() => toggleClass(item.id)}
              />
              {item.name}
            </label>
          ))}

          <label className="checkbox topics-toggle">
            <input
              type="checkbox"
              checked={showTopics}
              onChange={(event) => toggleTopics(event.target.checked)}
            />
            {t('agenda.topics')}
          </label>
        </div>
      )}

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

      {loading ? (
        <p>{t('common.loading')}</p>
      ) : mode === 'week' ? (
        renderWeek()
      ) : (
        renderMonth()
      )}

      <section className="panel agenda-summary">
        <strong>
          {t('agenda.summary', {
            period: t(mode === 'week' ? 'agenda.forWeek' : 'agenda.forMonth'),
            count: t('common.lessonCount', { count: summary.total }),
          })}
        </strong>
        {summary.cancelled > 0 && (
          <span className="hint">
            {t('agenda.summaryCancelled', { count: summary.cancelled })}
          </span>
        )}
        {Object.entries(summary.byClass).map(([name, count]) => (
          <span key={name} className="hint">
            {name}: {count}
          </span>
        ))}
        {!summary.total && <span className="hint">{t('agenda.noLessons')}</span>}
      </section>

      {dialog?.type === 'add' && (
        <AddLessonDialog
          date={dialog.date}
          number={dialog.number}
          classes={freeClassesFor(dialog.date, dialog.number)}
          busy={busy}
          onSubmit={handleAdd}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'copy' && (
        <CopyDialog
          source={copyRange}
          slots={copySource.slots}
          studyDates={copySource.studyDates}
          classes={visibleClasses}
          busy={busy}
          title={
            selection
              ? t('agenda.copySelected')
              : t(
                  mode === 'week'
                    ? 'agenda.copyWholeWeek'
                    : 'agenda.copyWholeMonth',
                )
          }
          note={t('agenda.copyNote')}
          onTargetChange={loadTarget}
          onSubmit={handleCopy}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'clear' && (
        <ClearDialog
          range={selection}
          slots={copySource.slots}
          classes={visibleClasses}
          busy={busy}
          onSubmit={handleClear}
          onClose={() => setDialog(null)}
        />
      )}

      {dialog?.type === 'lesson' && (
        <LessonMenu
          lesson={dialog.lesson}
          date={dialog.date}
          busy={busy}
          onCancel={(reason) =>
            patchLesson(dialog.date, dialog.lesson, { is_cancelled: true, reason })
          }
          onRestore={() =>
            patchLesson(dialog.date, dialog.lesson, { is_cancelled: false, reason: '' })
          }
          onDelete={() => removeLesson(dialog.date, dialog.lesson)}
          onClose={() => setDialog(null)}
        />
      )}
    </main>
  )
}
