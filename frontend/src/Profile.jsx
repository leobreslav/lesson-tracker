import { useEffect, useState } from 'react'
import { fetchMe, updateMe } from './api'

export default function Profile({ onLoggedOut, onSaved }) {
  const [user, setUser] = useState(null)
  const [form, setForm] = useState({ first_name: '', last_name: '' })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null) // {type: 'ok' | 'error', text}
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchMe()
      .then((data) => {
        if (cancelled) return
        setUser(data)
        setForm({ first_name: data.first_name, last_name: data.last_name })
      })
      .catch((err) => {
        if (err.status === 401) onLoggedOut()
        else if (!cancelled) setLoadError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [onLoggedOut])

  const handleChange = (event) => {
    const { name, value } = event.target
    setForm((prev) => ({ ...prev, [name]: value }))
    // прошлый результат больше не относится к тому, что в форме сейчас
    setMessage(null)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setMessage(null)

    try {
      const updated = await updateMe(form)
      setUser(updated)
      setForm({ first_name: updated.first_name, last_name: updated.last_name })
      // имя в баре меняется сразу вместе с профилем
      onSaved?.(updated)
      setMessage({ type: 'ok', text: 'Сохранено' })
    } catch (err) {
      if (err.status === 401) onLoggedOut()
      else setMessage({ type: 'error', text: err.message })
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <main className="card">
        <p className="error">{loadError}</p>
      </main>
    )
  }

  if (!user) {
    return (
      <main className="card">
        <p>Загрузка…</p>
      </main>
    )
  }

  return (
    <main className="card">
      <h1>Профиль</h1>

      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="email">Почта</label>
          {/* email приходит от Google и не редактируется */}
          <input id="email" type="email" value={user.email} readOnly />
          <p className="hint">Адрес берётся из аккаунта Google и не меняется.</p>
        </div>

        <div className="field">
          <label htmlFor="first_name">Имя</label>
          <input
            id="first_name"
            name="first_name"
            type="text"
            maxLength={150}
            value={form.first_name}
            onChange={handleChange}
            disabled={saving}
          />
        </div>

        <div className="field">
          <label htmlFor="last_name">Фамилия</label>
          <input
            id="last_name"
            name="last_name"
            type="text"
            maxLength={150}
            value={form.last_name}
            onChange={handleChange}
            disabled={saving}
          />
        </div>

        <div className="actions">
          <button type="submit" disabled={saving}>
            {saving ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>

        {message && (
          <p className={message.type === 'ok' ? 'success' : 'error'} role="status">
            {message.text}
          </p>
        )}
      </form>
    </main>
  )
}
