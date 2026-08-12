import { Link } from 'react-router-dom'

/** Главная. Навигация живёт в верхнем баре, здесь только приветствие. */
export default function Dashboard({ user }) {
  if (!user) {
    return (
      <main className="card">
        <p>Загрузка…</p>
      </main>
    )
  }

  const name = [user.first_name, user.last_name].filter(Boolean).join(' ')

  return (
    <main className="card">
      <h1>Трекер уроков</h1>
      <p>
        Вы вошли как <strong>{name || user.email}</strong>
        {name && <span className="hint"> ({user.email})</span>}
      </p>
      <p className="hint">
        Разделы — в верхнем баре. Начните с{' '}
        <Link to="/schedule">своего расписания</Link>: там видно, что и когда
        идёт по всем классам.
      </p>
    </main>
  )
}
