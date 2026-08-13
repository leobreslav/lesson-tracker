import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import {
  fetchCourses,
  fetchLayout,
  fetchLayoutSummary,
  fetchSchoolYears,
} from './api'
import { today } from './calendarLogic'
import { longDate, shortDate, shortWeekday } from './dates'
import { layoutBlocks } from './planLogic'

export default function Layout({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [classes, setClasses] = useState(null)
  const [years, setYears] = useState([])
  const [classId, setClassId] = useState(null)
  const [entries, setEntries] = useState(null)
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    let cancelled = false

    Promise.all([fetchCourses(), fetchSchoolYears()])
      .then(([classList, yearList]) => {
        if (cancelled) return
        setClasses(classList)
        setYears(yearList)
        setClassId((current) => current ?? classList[0]?.id ?? null)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  useEffect(() => {
    if (!classId) {
      setEntries(null)
      setSummary(null)
      return undefined
    }

    let cancelled = false
    setEntries(null)
    setError(null)

    // the layout is stored nowhere: every visit computes it again
    Promise.all([fetchLayout(classId), fetchLayoutSummary(classId)])
      .then(([layout, counters]) => {
        if (cancelled) return
        setEntries(layout.entries)
        setSummary(counters)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [classId, handleError])

  const yearById = useMemo(
    () => new Map(years.map((year) => [year.id, year])),
    [years],
  )

  const classLabel = (item) => {
    const year = yearById.get(item.year)
    return years.length > 1 && year ? `${item.name} · ${year.name}` : item.name
  }

  const placed = useMemo(
    () => (entries ?? []).filter((entry) => entry.slot),
    [entries],
  )
  const leftovers = useMemo(
    () => (entries ?? []).filter((entry) => entry.status === 'no_slot'),
    [entries],
  )

  /** The index the "today" line goes in front of. */
  const todayIndex = useMemo(() => {
    const now = today()
    const index = placed.findIndex((entry) => entry.slot.date >= now)
    return index === -1 ? placed.length : index
  }, [placed])

  /** Entries grouped into terms, in feed order. */
  const blocks = useMemo(() => {
    const result = []

    placed.forEach((entry, index) => {
      const key = entry.term_id ?? null
      if (result.at(-1)?.key !== key) {
        result.push({
          key,
          name: entry.term_name || t('layout.outsideTerms'),
          entries: [],
          firstIndex: index,
        })
      }
      result.at(-1).entries.push({ entry, index })
    })

    return result
  }, [placed, t])

  /** Counters per section block, computed from the layout already loaded. */
  const themeBlocks = useMemo(() => layoutBlocks(entries ?? []), [entries])

  /** A block's note: lessons, dates, leftovers and a crossing into a term. */
  const blockNote = (sectionId) => {
    const block = themeBlocks.byId.get(sectionId)
    if (!block) return null

    const parts = [t('common.lessonCount', { count: block.lessons })]
    if (block.missing) parts.push(t('layout.blockMissing', { count: block.missing }))

    const dates = block.first && `${shortDate(block.first)} — ${shortDate(block.last)}`
    const crossing =
      block.terms.length > 1 && t('layout.blockCrossing', { term: block.terms.at(-1) })

    return [parts.join(', '), dates, crossing].filter(Boolean).join(' · ')
  }

  const termSummary = useMemo(
    () => new Map((summary?.terms ?? []).map((row) => [row.id, row])),
    [summary],
  )

  const renderRows = (items) => {
    let theme // the previous lesson's section: a divider goes in on change
    const rows = []

    items.forEach(({ entry, index }) => {
      if (index === todayIndex) {
        rows.push(
          <li className="layout-today" key="today">
            {t('layout.today')}
          </li>,
        )
      }

      const lesson = entry.plan_row
      if (lesson) {
        const next = lesson.section_title ?? null
        if (next !== theme) {
          theme = next
          rows.push(
            <li className="layout-theme" key={`theme-${entry.slot.id}`}>
              {next ?? t('layout.noTheme')}
              {lesson.section_id != null && (
                <span className="hint block-count">
                  {blockNote(lesson.section_id)}
                </span>
              )}
            </li>,
          )
        }
      }

      rows.push(
        <li
          className={
            'layout-row' +
            (index < todayIndex ? ' past' : '') +
            (lesson ? '' : ' free') +
            (entry.slot.is_extra ? ' extra' : '')
          }
          key={entry.slot.id}
        >
          <span className="layout-date">
            {shortDate(entry.slot.date)} <em>{shortWeekday(entry.slot.date)}</em>
          </span>
          <span className="slot">{entry.slot.lesson_number}</span>
          <span className="layout-title">
            {lesson ? (
              <>
                <span className="plan-number">{lesson.number}.</span> {lesson.title}
              </>
            ) : (
              t('layout.freeSlot')
            )}
          </span>
          {entry.slot.is_extra && <span className="badge">{t('layout.extra')}</span>}
        </li>,
      )
    })

    return rows
  }

  if (classes === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('layout.title')}</h1>
      </header>

      {!classes.length ? (
        <EmptyState
          title={t('layout.needClass.title')}
          actions={
            <button type="button" onClick={() => navigate('/classes')}>
              {t('layout.needClass.action')}
            </button>
          }
        >
          {t('layout.needClass.hint')}
        </EmptyState>
      ) : (
        <>
          <div className="year-picker">
            {classes.map((item) => (
              <button
                type="button"
                key={item.id}
                className={item.id === classId ? 'chip active' : 'chip'}
                onClick={() => setClassId(item.id)}
              >
                {classLabel(item)}
              </button>
            ))}
          </div>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {summary && (
            <div className="cards">
              <section className="panel card-stat">
                <h2>{summary.remaining_slots}</h2>
                <p className="hint">{t('layout.remainingSlots')}</p>
              </section>
              <section className="panel card-stat">
                <h2>{summary.remaining_lessons}</h2>
                <p className="hint">{t('layout.remainingLessons')}</p>
              </section>
              <section
                className={`panel card-stat ${summary.balance < 0 ? 'bad' : 'good'}`}
              >
                <h2>
                  {summary.balance > 0 ? '+' : ''}
                  {summary.balance}
                </h2>
                <p className="hint">
                  {t(summary.balance < 0 ? 'layout.balanceShort' : 'layout.balanceSpare')}
                </p>
              </section>
              <section className="panel card-stat">
                <h2 className="small">
                  {summary.last_lesson_date
                    ? longDate(summary.last_lesson_date)
                    : '—'}
                </h2>
                <p className="hint">
                  {t(
                    summary.last_lesson_date
                      ? 'layout.lastLesson'
                      : 'layout.planDoesNotFit',
                  )}
                </p>
              </section>
            </div>
          )}

          {entries === null ? (
            <p>{t('common.loading')}</p>
          ) : (
            <>
              {themeBlocks.loose > 0 && (
                <p className="hint">{t('layout.loose', { count: themeBlocks.loose })}</p>
              )}

              {!placed.length && !leftovers.length && (
                <EmptyState
                  title={t('layout.nothing.title')}
                  actions={
                    <>
                      <button type="button" onClick={() => navigate('/plan')}>
                        {t('layout.nothing.fillPlan')}
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => navigate('/schedule')}
                      >
                        {t('layout.nothing.buildSchedule')}
                      </button>
                    </>
                  }
                >
                  {t('layout.nothing.hint')}
                </EmptyState>
              )}

              {blocks.map((block) => {
                const counters = termSummary.get(block.key)

                return (
                  <section className="term-block" key={block.key ?? 'outside'}>
                    <header className="term-head">
                      <strong>{block.name}</strong>
                      {counters?.start && (
                        <span className="hint">
                          {shortDate(counters.start)} — {shortDate(counters.end)}
                        </span>
                      )}
                      {counters && (
                        <span className="term-counters">
                          {t('layout.termCounters', {
                            slots: counters.slots,
                            lessons: counters.lessons,
                          })}{' '}
                          <b className={counters.balance < 0 ? 'bad' : 'good'}>
                            {counters.balance > 0 ? '+' : ''}
                            {counters.balance}
                          </b>
                        </span>
                      )}
                    </header>

                    <ul className="layout-feed">{renderRows(block.entries)}</ul>
                  </section>
                )
              })}

              {todayIndex === placed.length && placed.length > 0 && (
                <ul className="layout-feed">
                  <li className="layout-today">{t('layout.today')}</li>
                </ul>
              )}

              {leftovers.length > 0 && (
                <section className="panel leftovers">
                  <h3>{t('layout.leftovers.title')}</h3>
                  <p className="hint">{t('layout.leftovers.hint')}</p>
                  <ul className="layout-feed">
                    {leftovers.map((entry) => (
                      <li className="layout-row leftover" key={entry.plan_row.id}>
                        <span className="layout-title">
                          <span className="plan-number">{entry.plan_row.number}.</span>{' '}
                          {entry.plan_row.title}
                        </span>
                        {entry.plan_row.section_title && (
                          <span className="hint">{entry.plan_row.section_title}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {summary && (
                <p className="hint">
                  {t('layout.total', {
                    slots: summary.slots_total,
                    lessons: summary.lessons_total,
                    cancelled: summary.cancelled_count,
                    extra: summary.extra_count,
                  })}
                </p>
              )}
            </>
          )}
        </>
      )}
    </main>
  )
}
