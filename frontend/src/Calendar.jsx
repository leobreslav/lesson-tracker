import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CalendarGrid, { CalendarLegend } from './CalendarGrid'
import EmptyState from './EmptyState'
import Modal from './Modal'
import TermsPanel from './TermsPanel'
import RangeDialog from './RangeDialog'
import {
  createException,
  createTerm,
  deleteTerm,
  fetchTerms,
  updateTerm,
  createSchoolYear,
  deleteException,
  deleteSchoolYear,
  fetchSchoolYear,
  fetchSchoolYears,
  fetchYearDays,
  fetchYearStats,
  fetchYearUsage,
} from './api'
import {
  KIND_HOLIDAY,
  KIND_VACATION,
  KIND_WORKDAY,
  STATUS_STUDY,
  STATUS_WEEKEND,
  STATUSES,
  buildDays,
  buildStats,
  suggestVacations,
} from './calendarLogic'
import { dateRange, weekdayHeadings } from './dates'

/** The default school year: September of the nearest start to May after. */
function suggestYear() {
  const today = new Date()
  const start = today.getMonth() >= 5 ? today.getFullYear() : today.getFullYear() - 1

  return {
    name: `${start}/${start + 1}`,
    start_date: `${start}-09-01`,
    end_date: `${start + 1}-05-31`,
  }
}

/** Short label of a weekday by our number (Monday is 0). */
function weekdayLabel(weekday) {
  return weekdayHeadings().find((item) => item.weekday === weekday)?.label ?? ''
}

/**
 * The school year and its markup.
 *
 * The calendar belongs to the school: everybody reads the same one, only an
 * administrator edits it. For a teacher the page stays exactly as
 * informative and loses every control — the server refuses those calls
 * anyway, and a button that always fails is worse than no button.
 */
export default function Calendar({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const canEdit = Boolean(user?.is_school_admin)
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [year, setYear] = useState(null) // carries an `exceptions` field
  const [days, setDays] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [yearForm, setYearForm] = useState(null) // new-year form; null is closed
  const [rangeForm, setRangeForm] = useState(null) // {start_date, end_date, title}
  const [terms, setTerms] = useState([])
  // что унесёт удаление года: null — окно закрыто
  const [removing, setRemoving] = useState(null)

  // id of an optimistically added exception until the server answers
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
      Promise.all([
        fetchSchoolYear(id),
        fetchYearDays(id),
        fetchYearStats(id),
        fetchTerms(id),
      ]).then(([detail, calendar, counters, termList]) => {
        setYear(detail)
        setDays(calendar.days)
        setStats(counters)
        setTerms(termList)
      }),
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

  /** Recompute the grid and counters from a list of exceptions, offline. */
  const applyLocally = useCallback((source, list, termList = terms) => {
    // the server sorts exceptions by start date — keep the same order
    const exceptions = [...list].sort((a, b) => a.start_date.localeCompare(b.start_date))
    const next = buildDays(source, exceptions, termList)
    setYear({ ...source, exceptions })
    setDays(next)
    setStats(buildStats(next))
  }, [terms])

  /**
   * An optimistic edit: draw the result at once, confirm it with the
   * server's answer, and roll back to the previous markup on failure.
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
            t('calendar.exceptions.wholePeriod', {
              title: exception.title || t(`calendar.kind.${exception.kind}`),
            }),
          )
          return
        }
        removeException(exception)
        return
      }

      // a weekend becomes a working day (a moved lesson), a study day a holiday
      const kind = day.status === STATUS_WEEKEND ? KIND_WORKDAY : KIND_HOLIDAY
      addException({
        start_date: date,
        end_date: date,
        kind,
        // the title is saved to the database, so it is written in the
        // teacher's language, like every other piece of their content
        title: t(`calendar.kind.${kind}`),
      })
    },
    [saving, dayByDate, year, addException, removeException, t],
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
      title: title || t(`calendar.kind.${KIND_VACATION}`),
    })
  }

  /** Term edits are not optimistic: there are few, re-reading is simpler. */
  const runTerm = async (request) => {
    setError(null)
    setNotice(null)
    setSaving(true)

    try {
      await request()
      await load(yearId)
    } catch (err) {
      handleError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteTerm = (term) => {
    if (!window.confirm(t('calendar.terms.deleteConfirm', { name: term.name }))) return
    runTerm(() => deleteTerm(term.id))
  }

  const studyDaysByTerm = useMemo(
    () =>
      Object.fromEntries(
        (stats?.by_term ?? []).map((row) => [row.id, row.study]),
      ),
    [stats],
  )

  /**
   * Typical breaks behind one button.
   *
   * They are not created silently: every school has its own dates, so we
   * offer them and show what came out — from there it edits like any markup.
   */
  const addTypicalVacations = () => {
    const startYear = Number(year.start_date.slice(0, 4))
    const titles = {
      autumn: t('calendar.typicalVacations.autumn'),
      winter: t('calendar.typicalVacations.winter'),
      spring: t('calendar.typicalVacations.spring'),
    }
    const wanted = suggestVacations(startYear, titles).filter(
      (item) => item.start_date >= year.start_date && item.end_date <= year.end_date,
    )

    runTerm(async () => {
      for (const vacation of wanted) {
        await createException({
          ...vacation,
          kind: KIND_VACATION,
          year: year.id,
        })
      }
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

  /**
   * Удаление года спрашивают окном, а не `confirm`, и с числами.
   *
   * Каскад уносит курсы школы, а с ними назначения и всё школьное
   * расписание — «удалить разметку?» об этом умалчивало. Числа берём с
   * сервера: только он знает, что там накопилось.
   */
  const askDeleteYear = async () => {
    setSaving(true)
    try {
      setRemoving(await fetchYearUsage(year.id))
    } catch (err) {
      handleError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteYear = async () => {
    setSaving(true)
    try {
      await deleteSchoolYear(year.id)
      const rest = years.filter((item) => item.id !== year.id)
      setYears(rest)
      setYearId(rest[0]?.id ?? null)
      setRemoving(null)
    } catch (err) {
      handleError(err)
      setRemoving(null)
    } finally {
      setSaving(false)
    }
  }

  if (years === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('calendar.title')}</h1>
      </header>

      {!canEdit && <p className="hint">{t('calendar.readOnly')}</p>}

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
        {canEdit && (
          <button
            type="button"
            className="chip"
            onClick={() => setYearForm(yearForm ? null : suggestYear())}
          >
            {yearForm ? t('common.cancel') : t('calendar.newYear')}
          </button>
        )}
      </div>

      {yearForm && (
        <form className="inline-form" onSubmit={handleCreateYear}>
          <div className="field">
            <label htmlFor="year-name">{t('calendar.nameLabel')}</label>
            <input
              id="year-name"
              value={yearForm.name}
              maxLength={64}
              required
              onChange={(e) => setYearForm({ ...yearForm, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="year-start">{t('calendar.startLabel')}</label>
            <input
              id="year-start"
              type="date"
              value={yearForm.start_date}
              required
              onChange={(e) => setYearForm({ ...yearForm, start_date: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="year-end">{t('calendar.endLabel')}</label>
            <input
              id="year-end"
              type="date"
              value={yearForm.end_date}
              required
              onChange={(e) => setYearForm({ ...yearForm, end_date: e.target.value })}
            />
          </div>
          <button type="submit" disabled={saving}>
            {t('calendar.create')}
          </button>
        </form>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="hint" role="status">{notice}</p>}

      {!years.length && !yearForm && (
        <EmptyState
          title={t('calendar.empty.title')}
          actions={
            canEdit && (
              <button type="button" onClick={() => setYearForm(suggestYear())}>
                {t('calendar.empty.action')}
              </button>
            )
          }
        >
          {t(canEdit ? 'calendar.empty.hint' : 'calendar.empty.askAdmin')}
        </EmptyState>
      )}

      {loading && <p>{t('calendar.loadingCalendar')}</p>}

      {year && !loading && (
        <>
          {/* легенда над обеими колонками: те же квадратики стоят и в
              сводке справа, а внутри левой колонки она сдвигала
              календари вниз — колонки начинались на разной высоте */}
          <CalendarLegend terms={terms} />

          <div className="calendar-layout">
            <CalendarGrid
              days={days}
              terms={terms}
              pending={rangeForm}
              onToggleDay={handleToggleDay}
              onSelectRange={handleSelectRange}
              disabled={saving || !canEdit}
            />

            <aside className="calendar-side">
              <section className="panel">
                <h2>{stats ? stats.total : '—'}</h2>
                <p className="hint">
                  {t('calendar.studyDaysOf', {
                    start: year.start_date,
                    end: year.end_date,
                  })}
                </p>
                {stats && (
                  <>
                    <table className="weekday-stats">
                      <tbody>
                        {stats.by_weekday
                          .filter((row) => row.count > 0)
                          .map((row) => (
                            <tr key={row.weekday}>
                              <th scope="row">{weekdayLabel(row.weekday)}</th>
                              <td>{row.count}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>

                    {/* every day of the year lands in exactly one row */}
                    <table className="weekday-stats status-stats">
                      <tbody>
                        {STATUSES.filter((status) => status !== STATUS_STUDY).map(
                          (status) => (
                            <tr key={status}>
                              <th scope="row">
                                <span className={`swatch ${status}`} aria-hidden="true" />
                                {t(`dayStatus.${status}`)}
                              </th>
                              <td>{stats.by_status[status]}</td>
                            </tr>
                          ),
                        )}
                        <tr>
                          <th scope="row">{t('calendar.totalDays')}</th>
                          <td>{stats.calendar_days}</td>
                        </tr>
                      </tbody>
                    </table>
                  </>
                )}
              </section>

              <TermsPanel
                terms={terms}
                year={year}
                studyDays={studyDaysByTerm}
                busy={saving}
                canEdit={canEdit}
                onCreate={(fields) => runTerm(() => createTerm({ ...fields, year: year.id }))}
                onUpdate={(id, fields) => runTerm(() => updateTerm(id, fields))}
                onDelete={handleDeleteTerm}
              />

              <section className="panel">
                <h3>{t('calendar.exceptions.title')}</h3>
                {canEdit && !year.exceptions.length && (
                  <p className="hint">
                    <button
                      type="button"
                      className="secondary"
                      disabled={saving}
                      onClick={addTypicalVacations}
                    >
                      {t('calendar.exceptions.typical')}
                    </button>{' '}
                    {t('calendar.exceptions.typicalHint')}
                  </p>
                )}
                {canEdit && !year.exceptions.length && (
                  <p className="hint">{t('calendar.exceptions.hint')}</p>
                )}
                <ul className="exceptions">
                  {year.exceptions.map((exception) => (
                    <li key={exception.id} className={exception.kind}>
                      <div>
                        <strong>
                          {exception.title || t(`calendar.kind.${exception.kind}`)}
                        </strong>
                        <span className="hint">
                          {t(`calendar.kind.${exception.kind}`)},{' '}
                          {dateRange(exception.start_date, exception.end_date)}
                        </span>
                      </div>
                      {canEdit && (
                        <button
                          type="button"
                          className="link"
                          disabled={saving}
                          onClick={() => removeException(exception)}
                          aria-label={t('calendar.exceptions.delete')}
                        >
                          ✕
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>

              {canEdit && (
                <button
                  type="button"
                  className="secondary"
                  disabled={saving}
                  onClick={askDeleteYear}
                >
                  {t('calendar.deleteYear')}
                </button>
              )}
            </aside>
          </div>
        </>
      )}

      {rangeForm && (
        <RangeDialog
          range={rangeForm}
          busy={saving}
          onSubmit={handleCreateVacation}
          onCancel={() => setRangeForm(null)}
        />
      )}

      {removing && (
        <Modal onClose={() => setRemoving(null)}>
          <h3>{t('calendar.removeYear.title', { name: year.name })}</h3>

          {removing.slots || removing.plan_rows ? (
            /* уроки и планы держат курсы через PROTECT: сервер откажет, и
               сказать об этом лучше здесь, чем показать ошибку после нажатия */
            <>
              <p className="hint warning">
                {t('calendar.removeYear.blocked', {
                  slots: removing.slots,
                  rows: removing.plan_rows,
                })}
              </p>
              <div className="actions">
                <button type="button" onClick={() => setRemoving(null)}>
                  {t('common.close')}
                </button>
              </div>
            </>
          ) : (
            <>
              <p>{t('calendar.removeYear.hint')}</p>
              <ul className="loss-list">
                {[
                  ['courses', removing.courses],
                  ['assignments', removing.assignments],
                  ['terms', removing.terms],
                  ['exceptions', removing.exceptions],
                ]
                  .filter(([, count]) => count > 0)
                  .map(([key, count]) => (
                    <li key={key}>{t(`calendar.removeYear.${key}`, { count })}</li>
                  ))}
              </ul>
              <div className="actions">
                <button type="button" disabled={saving} onClick={handleDeleteYear}>
                  {t('calendar.removeYear.confirm')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setRemoving(null)}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </main>
  )
}
