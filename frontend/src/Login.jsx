import { useEffect, useRef, useState } from 'react'
import { loginWithGoogle, setToken } from './api'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

export default function Login({ onLoggedIn }) {
  const buttonRef = useRef(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!CLIENT_ID) {
      setError('Не задан VITE_GOOGLE_CLIENT_ID в frontend/.env')
      return
    }

    // скрипт GIS грузится асинхронно из index.html — дожидаемся его
    const timer = setInterval(() => {
      if (!window.google?.accounts?.id || !buttonRef.current) return
      clearInterval(timer)

      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async ({ credential }) => {
          try {
            const { key } = await loginWithGoogle(credential)
            setToken(key)
            onLoggedIn()
          } catch (err) {
            setError(err.message)
          }
        },
      })
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: 'outline',
        size: 'large',
        text: 'signin_with',
        locale: 'ru',
      })
    }, 100)

    return () => clearInterval(timer)
  }, [onLoggedIn])

  return (
    <main className="card">
      <h1>Трекер уроков</h1>
      <p>Войдите, чтобы продолжить.</p>
      <div ref={buttonRef} />
      {error && <p className="error">{error}</p>}
    </main>
  )
}
