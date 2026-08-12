import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CalendarGrid from './CalendarGrid'
import RangeDialog from './RangeDialog'
import {
  createException,
  createSchoolYear,
  deleteException,
  deleteSchoolYear,
  fetchSchoolYear,
  fetchSchoolYears,
  fetchYearDays,
  fetchYearStats,
} from './api'
import {
  KIND_HOLIDAY,
  KIND_LABELS,
  KIND_VACATION,
  KIND_WORKDAY,
  STATUS_LABELS,
  STATUS_STUDY,
  STATUS_WEEKEND,
  STATUSES,
  WEEKDAY_SHORT,
  buildDays,
  buildStats,
  formatRange,
} from './calendarLogic'

/** Учебный год по умолчанию: сентябрь ближайшего начала — май следующего. */
function suggestYear() {
  const today = new Date()
  const start = today.getMonth() >= 5 ? today.getFullYear() : today.getFullYear() - 1

  return {
    name: `${start}/${start + 1}`,
    start_date: `${start}-09-01`,
    end_date: `${start + 1}-05-31`,
  }
}

export default function Calendar({ onLoggedOut }) {
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [year, setYear] = useState(null) // с полем exceptions
  const [days, setDays] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [yearForm, setYearForm] = useState(null) // форма нового года, null — закрыта
  const [rangeForm, setRangeForm] = useState(null) // {start_date, end_date, title}

  // id для оптимистично добавленного исключения, пока сервер не ответил
  const tempId = useRef(0)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    let cancelled = false

    fetchSchoolYears()
      .then((list) => {
        if (cancelled) return
        setYears(list)
        setYearId((current) => current ?? list[0]?.id ?? null)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  const load = useCallback(
    (id) =>
      Promise.all([fetchSchoolYear(id), fetchYearDays(id), fetchYearStats(id)]).then(
        ([detail, calendar, counters]) => {
          setYear(detail)
          setDays(calendar.days)
          setStats(counters)
        },
      ),
    [],
  )

  useEffect(() => {
    if (!yearId) {
      setYear(null)
      setDays([])
      setStats(null)
      return undefined
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    load(yearId)
      .catch((err) => {
        if (!cancelled) handleError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [yearId, load, handleError])

  /** Пересчитать сетку и счётчики по списку исключений, не спрашивая сервер. */
  const applyLocally = useCallback((source, list) => {
    // сервер отдаёт исключения по дате начала — держим тот же порядок
    const exceptions = [...list].sort((a, b) => a.start_date.localeCompare(b.start_date))
    const next = buildDays(source, exceptions)
    setYear({ ...source, exceptions })
    setDays(next)
    setStats(buildStats(next))
  }, [])

  /**
   * Оптимистичная правка: сразу рисуем результат, потом подтверждаем ответом
   * сервера, а при ошибке возвращаем прежнюю разметку.
   */
  const mutate = useCallback(
    async (exceptions, request) => {
      const snapshot = year
      setError(null)
      setNotice(null)
      setSaving(true)
      applyLocally(snapshot, exceptions)

      try {
        await request()
        await load(snapshot.id)
      } catch (err) {
        applyLocally(snapshot, snapshot.exceptions)
        handleError(err)
      } finally {
        setSaving(false)
      }
    },
    [year, applyLocally, load, handleError],
  )

  const addException = useCallback(
    (fields) => {
      tempId.current -= 1
      const optimistic = { ...fields, id: tempId.current }

      return mutate([...year.exceptions, optimistic], () =>
        createException({ ...fields, year: year.id }),
      )
    },
    [year, mutate],
  )

  const removeException = useCallback(
    (exception) =>
      mutate(
        year.exceptions.filter((item) => item.id !== exception.id),
        () => deleteException(exception.id),
      ),
    [year, mutate],
  )

  const dayByDate = useMemo(
    () => new Map(days.map((day) => [day.date, day])),
    [days],
  )

  const handleToggleDay = useCallback(
    (date) => {
      if (saving) return
      const day = dayByDate.get(date)
      if (!day) return

      const exception = year.exceptions.find((item) => item.id === day.exception)

      if (exception) {
        if (exception.start_date !== exception.end_date) {
          setNotice(
            `«${exception.title || KIND_LABELS[exception.kind]}» — период целиком, ` +
              'удалите его в списке справа.',
          )
          return
        }
        removeException(exception)
        return
      }

      // выходной делаем рабочим (перенос), обычный учебный — праздником
      const kind = day.status === STATUS_WEEKEND ? KIND_WORKDAY : KIND_HOLIDAY
      addException({
        start_date: date,
        end_date: date,
        kind,
        title: KIND_LABELS[kind],
      })
    },
    [saving, dayByDate, year, addException, removeException],
  )

  const handleSelectRange = useCallback(
    (from, to) => {
      if (saving) return
      setNotice(null)
      setRangeForm({ start_date: from, end_date: to })
    },
    [saving],
  )

  const handleCreateVacation = async (title) => {
    const { start_date, end_date } = rangeForm
    setRangeForm(null)
    await addException({
      start_date,
      end_date,
      kind: KIND_VACATION,
      title: title || KIND_LABELS[KIND_VACATION],
    })
  }

  const handleCreateYear = async (event) => {
    event.preventDefault()
    setError(null)
    setSaving(true)

    try {
      const created = await createSchoolYear(yearForm)
      setYears((list) => [created, ...list])
      setYearForm(null)
      setYearId(created.id)
    } catch (err) {
      handleError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteYear = async () => {
    if (!window.confirm(`Удалить учебный год «${year.name}» вместе с разметкой?`)) return

    setSaving(true)
    try {
      await deleteSchoolYear(year.id)
      const rest = years.filter((item) => item.id !== year.id)
      setYears(rest)
      setYearId(rest[0]?.id ?? null)
    } catch (err) {
      handleError(err)
    } finally {
      setSaving(false)
    }
  }

  if (years === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : 'Загрузка…'}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Учебный год</h1>
      </header>

      <div className="year-picker">
        {years.map((item) => (
          <button
            type="button"
            key={item.id}
            className={item.id === yearId ? 'chip active' : 'chip'}
            onClick={() => setYearId(item.id)}
          >
            {item.name}
          </button>
        ))}
        <button
          type="button"
          className="chip"
          onClick={() => setYearForm(yearForm ? null : suggestYear())}
        >
          {yearForm ? 'Отмена' : '+ Новый год'}
        </button>
      </div>

      {yearForm && (
        <form className="inline-form" onSubmit={handleCreateYear}>
          <div className="field">
            <label htmlFor="year-name">Название</label>
            <input
              id="year-name"
              value={yearForm.name}
              maxLength={64}
              required
              onChange={(e) => setYearForm({ ...yearForm, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="year-start">Начало</label>
            <input
              id="year-start"
              type="date"
              value={yearForm.start_date}
              required
              onChange={(e) => setYearForm({ ...yearForm, start_date: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="year-end">Конец</label>
            <input
              id="year-end"
              type="date"
              value={yearForm.end_date}
              required
              onChange={(e) => setYearForm({ ...yearForm, end_date: e.target.value })}
            />
          </div>
          <button type="submit" disabled={saving}>
            Создать
          </button>
        </form>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="hint" role="status">{notice}</p>}

      {!years.length && !yearForm && (
        <p className="hint">Пока нет ни одного учебного года — создайте первый.</p>
      )}

      {loading && <p>Загрузка календаря…</p>}

      {year && !loading && (
        <div className="calendar-layout">
          <CalendarGrid
            days={days}
            pending={rangeForm}
            onToggleDay={handleToggleDay}
            onSelectRange={handleSelectRange}
            disabled={saving}
          />

          <aside className="calendar-side">
            <section className="panel">
              <h2>{stats ? stats.total : '—'}</h2>
              <p className="hint">учебных дней с {year.start_date} по {year.end_date}</p>
              {stats && (
                <>
                  <table className="weekday-stats">
                    <tbody>
                      {stats.by_weekday
                        .filter((row) => row.count > 0)
                        .map((row) => (
                          <tr key={row.weekday}>
                            <th scope="row">{WEEKDAY_SHORT[row.weekday]}</th>
                            <td>{row.count}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>

                  {/* каждый день года попадает ровно в одну строку */}
                  <table className="weekday-stats status-stats">
                    <tbody>
                      {STATUSES.filter((status) => status !== STATUS_STUDY).map(
                        (status) => (
                          <tr key={status}>
                            <th scope="row">
                              <span className={`swatch ${status}`} aria-hidden="true" />
                              {STATUS_LABELS[status]}
                            </th>
                            <td>{stats.by_status[status]}</td>
                          </tr>
                        ),
                      )}
                      <tr>
                        <th scope="row">всего дней</th>
                        <td>{stats.calendar_days}</td>
                      </tr>
                    </tbody>
                  </table>
                </>
              )}
            </section>

            <section className="panel">
              <h3>Исключения</h3>
              {!year.exceptions.length && (
                <p className="hint">
                  Кликните по дню, чтобы отметить праздник, или протяните мышью
                  по нескольким дням — получатся каникулы.
                </p>
              )}
              <ul className="exceptions">
                {year.exceptions.map((exception) => (
                  <li key={exception.id} className={exception.kind}>
                    <div>
                      <strong>{exception.title || KIND_LABELS[exception.kind]}</strong>
                      <span className="hint">
                        {KIND_LABELS[exception.kind]},{' '}
                        {formatRange(exception.start_date, exception.end_date)}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="link"
                      disabled={saving}
                      onClick={() => removeException(exception)}
                      aria-label="Удалить исключение"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <button
              type="button"
              className="secondary"
              disabled={saving}
              onClick={handleDeleteYear}
            >
              Удалить год
            </button>
          </aside>
        </div>
      )}

      {rangeForm && (
        <RangeDialog
          range={rangeForm}
          busy={saving}
          onSubmit={handleCreateVacation}
          onCancel={() => setRangeForm(null)}
        />
      )}
    </main>
  )
}
