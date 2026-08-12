import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import { fetchCourses, fetchSchoolYears, fetchSlotStats } from './api'

/**
 * The courses of the school, as a teacher sees them.
 *
 * Read-only on purpose: a course belongs to the school and is created by an
 * administrator, so two colleagues teaching the same group share one entry
 * instead of inventing two. What is personal here are the counters — every
 * teacher sees their own lessons inside the shared course.
 */
export default function Classes({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  // lesson counters per course: {id: {total, past, remaining, cancelled}}
  const [stats, setStats] = useState({})

  const isAdmin = Boolean(user?.is_school_admin)

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
        // a single year needs no picking
        setYearId((current) => current ?? list[0]?.id ?? null)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  /**
   * Lesson counters for every course.
   *
   * The stats endpoint works one course at a time, and a year holds a handful
   * of them — asking for all of them is simpler than inventing a new API.
   */
  const loadStats = useCallback((list) => {
    if (!list.length) {
      setStats({})
      return Promise.resolve()
    }

    return Promise.all(
      list.map((item) =>
        fetchSlotStats(item.id)
          .then((data) => [item.id, data])
          .catch(() => [item.id, null]),
      ),
    ).then((pairs) => setStats(Object.fromEntries(pairs)))
  }, [])

  useEffect(() => {
    if (!yearId) {
      setItems(null)
      return undefined
    }

    let cancelled = false
    setItems(null)
    setError(null)

    fetchCourses(yearId)
      .then((list) => {
        if (cancelled) return
        setItems(list)
        return loadStats(list)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [yearId, handleError, loadStats])

  if (years === null) {
    return (
      <main className="page narrow">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('classes.title')}</h1>
      </header>

      {!years.length ? (
        <EmptyState
          title={t('classes.needYear.title')}
          actions={
            isAdmin && (
              <button type="button" onClick={() => navigate('/school')}>
                {t('classes.needYear.action')}
              </button>
            )
          }
        >
          {t(isAdmin ? 'classes.needYear.hint' : 'classes.needYear.askAdmin')}
        </EmptyState>
      ) : (
        <>
          <div className="year-picker">
            {years.map((year) => (
              <button
                type="button"
                key={year.id}
                className={year.id === yearId ? 'chip active' : 'chip'}
                onClick={() => setYearId(year.id)}
              >
                {year.name}
              </button>
            ))}
          </div>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {items === null && <p>{t('common.loading')}</p>}

          {items !== null && !items.length && (
            <EmptyState
              title={t('classes.empty.title')}
              actions={
                isAdmin && (
                  <button type="button" onClick={() => navigate('/school')}>
                    {t('classes.empty.action')}
                  </button>
                )
              }
            >
              {t(isAdmin ? 'classes.empty.hintAdmin' : 'classes.empty.hint')}
            </EmptyState>
          )}

          {items !== null && items.length > 0 && (
            <>
              <ul className="class-list">
                {items.map((item) => (
                  <li key={item.id}>
                    <span className="name">{item.name}</span>
                    {stats[item.id] && (
                      <span className="class-stats hint">
                        {t('classes.stats', stats[item.id])}
                      </span>
                    )}
                  </li>
                ))}
              </ul>

              <p className="hint">
                {t(isAdmin ? 'classes.manageHint' : 'classes.readOnlyHint')}
                {isAdmin && (
                  <>
                    {' '}
                    <button
                      type="button"
                      className="link"
                      onClick={() => navigate('/school')}
                    >
                      {t('nav.school')}
                    </button>
                  </>
                )}
              </p>
            </>
          )}
        </>
      )}
    </main>
  )
}
