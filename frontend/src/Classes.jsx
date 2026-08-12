import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createClass,
  deleteClass,
  fetchClasses,
  fetchSchoolYears,
  fetchSlotStats,
  renameClass,
} from './api'

export default function Classes({ onLoggedOut }) {
  const navigate = useNavigate()
  const [years, setYears] = useState(null)
  const [yearId, setYearId] = useState(null)
  const [items, setItems] = useState(null)
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(null) // {id, value}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // счётчики уроков по классам: {id: {total, past, remaining, cancelled}}
  const [stats, setStats] = useState({})

  // Escape закрывает редактирование сам, повторное сохранение по blur не нужно
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
        // год всего один — выбирать нечего
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
   * Счётчики уроков по каждому классу.
   *
   * Эндпоинт статистики работает по одному классу, а классов в году
   * единицы — проще спросить всех разом, чем городить новый API.
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
        [...list, created].sort((a, b) => a.name.localeCompare(b.name, 'ru')),
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
          .sort((a, b) => a.name.localeCompare(b.name, 'ru')),
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
    if (!window.confirm(`Удалить класс «${item.name}»?`)) return

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
        <p>{error ? <span className="error">{error}</span> : 'Загрузка…'}</p>
      </main>
    )
  }

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>Классы</h1>
      </header>

      {!years.length ? (
        <div className="panel">
          <p>Классы заводятся внутри учебного года, а его пока нет.</p>
          <button type="button" onClick={() => navigate('/year')}>
            Создать учебный год
          </button>
        </div>
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
            {/* submit по Enter даёт форма, отдельный обработчик не нужен */}
            <input
              value={name}
              maxLength={20}
              placeholder="Название класса, например 9Б"
              aria-label="Название класса"
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
            <button type="submit" disabled={busy || !name.trim()}>
              Добавить
            </button>
          </form>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {items === null && <p>Загрузка…</p>}

          {items !== null && !items.length && (
            <p className="hint">
              В этом году ещё нет классов. Заведите первый — введите название
              выше и нажмите Enter.
            </p>
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
                      aria-label="Новое название класса"
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
                        title="Переименовать"
                        disabled={busy}
                        onClick={() => startEdit(item)}
                      >
                        {item.name}
                      </button>
                      {stats[item.id] && (
                        <span className="class-stats hint">
                          уроков {stats[item.id].total} · прошло{' '}
                          {stats[item.id].past} · осталось{' '}
                          {stats[item.id].remaining} · отменено{' '}
                          {stats[item.id].cancelled}
                        </span>
                      )}
                    </>
                  )}

                  <button
                    type="button"
                    className="link"
                    aria-label={`Удалить класс ${item.name}`}
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
