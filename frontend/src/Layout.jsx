import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchClasses,
  fetchLayout,
  fetchLayoutSummary,
  fetchSchoolYears,
} from './api'
import { WEEKDAY_SHORT, parseDate, today, weekdayOf } from './calendarLogic'

const KIND_LABELS = { control: 'контрольная', reserve: 'резерв' }

function formatDate(iso) {
  return parseDate(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
  })
}

function formatLong(iso) {
  return iso
    ? parseDate(iso).toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      })
    : '—'
}

export default function Layout({ onLoggedOut }) {
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

    Promise.all([fetchClasses(), fetchSchoolYears()])
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

    // раскладка нигде не хранится: каждый заход считает её заново
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

  /** Перед каким индексом рисовать черту «сегодня». */
  const todayIndex = useMemo(() => {
    const now = today()
    const index = placed.findIndex((entry) => entry.slot.date >= now)
    return index === -1 ? placed.length : index
  }, [placed])

  const renderFeed = () => {
    let theme // тема предыдущего урока: разделитель ставим при смене
    const rows = []

    placed.forEach((entry, index) => {
      if (index === todayIndex) {
        rows.push(
          <li className="layout-today" key="today">
            сегодня
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
              {next ?? 'без темы'}
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
            {formatDate(entry.slot.date)}{' '}
            <em>{WEEKDAY_SHORT[weekdayOf(entry.slot.date)]}</em>
          </span>
          <span className="slot">{entry.slot.lesson_number}</span>
          <span className="layout-title">
            {lesson ? (
              <>
                <span className="plan-number">{lesson.number}.</span> {lesson.title}
              </>
            ) : (
              'свободный урок'
            )}
          </span>
          {lesson && KIND_LABELS[lesson.kind] && (
            <span className={`badge ${lesson.kind}`}>{KIND_LABELS[lesson.kind]}</span>
          )}
          {entry.slot.is_extra && <span className="badge">дополнительный</span>}
        </li>,
      )
    })

    if (todayIndex === placed.length) {
      rows.push(
        <li className="layout-today" key="today">
          сегодня
        </li>,
      )
    }

    return rows
  }

  if (classes === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : 'Загрузка…'}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Раскладка</h1>
      </header>

      {!classes.length ? (
        <div className="panel">
          <p>Раскладка считается для класса, а классов пока нет.</p>
          <button type="button" onClick={() => navigate('/plan')}>
            К учебному плану
          </button>
        </div>
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
                <p className="hint">слотов осталось</p>
              </section>
              <section className="panel card-stat">
                <h2>{summary.remaining_lessons}</h2>
                <p className="hint">уроков по плану осталось</p>
              </section>
              <section
                className={`panel card-stat ${summary.balance < 0 ? 'bad' : 'good'}`}
              >
                <h2>
                  {summary.balance > 0 ? '+' : ''}
                  {summary.balance}
                </h2>
                <p className="hint">
                  {summary.balance < 0 ? 'уроков не помещается' : 'запас слотов'}
                </p>
              </section>
              <section className="panel card-stat">
                <h2 className="small">{formatLong(summary.last_lesson_date)}</h2>
                <p className="hint">
                  {summary.last_lesson_date
                    ? 'последний урок по плану'
                    : 'план не помещается в год'}
                </p>
              </section>
            </div>
          )}

          {entries === null ? (
            <p>Загрузка…</p>
          ) : (
            <>
              {!placed.length && !leftovers.length && (
                <p className="hint">
                  Пока нечего раскладывать: нужен учебный план и расписание.
                </p>
              )}

              <ul className="layout-feed">{renderFeed()}</ul>

              {leftovers.length > 0 && (
                <section className="panel leftovers">
                  <h3>Не помещаются в год</h3>
                  <p className="hint">
                    Этим урокам плана не хватило слотов — добавьте занятия или
                    сократите план.
                  </p>
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
                  Всего слотов {summary.slots_total}, уроков плана{' '}
                  {summary.lessons_total}; отменено {summary.cancelled_count},
                  дополнительных {summary.extra_count}. Раскладка считается на
                  лету и меняется сама вслед за планом и расписанием.
                </p>
              )}
            </>
          )}
        </>
      )}
    </main>
  )
}
