import { useEffect, useState } from 'react'
import { fetchMe, logout } from './api'

export default function Dashboard({ onLoggedOut }) {
  const [user, setUser] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    fetchMe()
      .then((data) => {
        if (!cancelled) setUser(data)
      })
      .catch((err) => {
        // токен протух или отозван — возвращаем на логин
        if (err.status === 401) onLoggedOut()
        else if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [onLoggedOut])

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      onLoggedOut()
    }
  }

  if (error) return <main className="card"><p className="error">{error}</p></main>
  if (!user) return <main className="card"><p>Загрузка…</p></main>

  return (
    <main className="card">
      <h1>Трекер уроков</h1>
      <p>
        Вы вошли как <strong>{user.email}</strong>
      </p>
      <button onClick={handleLogout}>Выйти</button>
    </main>
  )
}
