import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import {
  createClass,
  deleteClass,
  fetchClasses,
  fetchSchoolYears,
  fetchSlotStats,
  renameClass,
} from './api'

export default function Classes({ onLoggedOut }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [items, setItems] = useState(null)
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(null) // {id, value}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // lesson counters per class: {id: {total, past, remaining, cancelled}}
  const [stats, setStats] = useState({})

  // Escape closes the editor itself; blur must not save a second time
  const skipBlur = useRef(false)

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
   * Lesson counters for every class.
   *
   * The stats endpoint works one class at a time, and a year holds a handful
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

    fetchClasses(yearId)
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

  const handleAdd = async (event) => {
    event.preventDefault()
    const value = name.trim()
    if (!value || busy) return

    setBusy(true)
    setError(null)

    try {
      const created = await createClass({ year: yearId, name: value })
      setItems((list) =>
        [...list, created].sort((a, b) => a.name.localeCompare(b.name, i18n.language)),
      )
      setName('')
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (item) => {
    skipBlur.current = false
    setError(null)
    setEditing({ id: item.id, value: item.name })
  }

  const commitEdit = async () => {
    if (!editing) return

    const { id, value } = editing
    const previous = items.find((item) => item.id === id)
    const trimmed = value.trim()
    setEditing(null)

    if (!trimmed || trimmed === previous.name) return

    setBusy(true)
    setError(null)

    try {
      const updated = await renameClass(id, trimmed)
      setItems((list) =>
        list
          .map((item) => (item.id === id ? updated : item))
          .sort((a, b) => a.name.localeCompare(b.name, i18n.language)),
      )
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const handleEditKeyDown = (event) => {
    if (event.key === 'Escape') {
      skipBlur.current = true
      setEditing(null)
    }
    if (event.key === 'Enter') {
      skipBlur.current = true
      event.preventDefault()
      commitEdit()
    }
  }

  const handleDelete = async (item) => {
    if (!window.confirm(t('classes.deleteConfirm', { name: item.name }))) return

    setBusy(true)
    setError(null)

    try {
      await deleteClass(item.id)
      setItems((list) => list.filter((entry) => entry.id !== item.id))
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

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
            <button type="button" onClick={() => navigate('/year')}>
              {t('classes.needYear.action')}
            </button>
          }
        >
          {t('classes.needYear.hint')}
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

          <form className="add-form" onSubmit={handleAdd}>
            {/* the form submits on Enter; no separate handler needed */}
            <input
              value={name}
              maxLength={20}
              placeholder={t('classes.placeholder')}
              aria-label={t('classes.nameLabel')}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
            <button type="submit" disabled={busy || !name.trim()}>
              {t('common.add')}
            </button>
          </form>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {items === null && <p>{t('common.loading')}</p>}

          {items !== null && !items.length && (
            <EmptyState title={t('classes.empty.title')}>
              {t('classes.empty.hint')}
            </EmptyState>
          )}

          {items !== null && items.length > 0 && (
            <ul className="class-list">
              {items.map((item) => (
                <li key={item.id}>
                  {editing?.id === item.id ? (
                    <input
                      autoFocus
                      value={editing.value}
                      maxLength={20}
                      aria-label={t('classes.newNameLabel')}
                      onChange={(event) =>
                        setEditing({ ...editing, value: event.target.value })
                      }
                      onKeyDown={handleEditKeyDown}
                      onBlur={() => {
                        if (!skipBlur.current) commitEdit()
                      }}
                    />
                  ) : (
                    <>
                      <button
                        type="button"
                        className="link name"
                        title={t('classes.rename')}
                        disabled={busy}
                        onClick={() => startEdit(item)}
                      >
                        {item.name}
                      </button>
                      {stats[item.id] && (
                        <span className="class-stats hint">
                          {t('classes.stats', stats[item.id])}
                        </span>
                      )}
                    </>
                  )}

                  <button
                    type="button"
                    className="link"
                    aria-label={t('classes.delete', { name: item.name })}
                    disabled={busy}
                    onClick={() => handleDelete(item)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  )
}
