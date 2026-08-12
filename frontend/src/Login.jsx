import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { loginWithGoogle, setToken } from './api'
import i18n, { browserLanguage } from './i18n'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

export default function Login({ onLoggedIn }) {
  const { t } = useTranslation()
  const buttonRef = useRef(null)
  const [error, setError] = useState(null)

  // nobody has signed in yet, so there is no profile to ask: the browser
  // decides, and anything we do not speak falls back to English
  useEffect(() => {
    i18n.changeLanguage(browserLanguage())
  }, [])

  useEffect(() => {
    if (!CLIENT_ID) {
      setError(t('auth.missingClientId'))
      return
    }

    // the GIS script loads asynchronously from index.html — wait for it
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
        locale: i18n.language,
      })
    }, 100)

    return () => clearInterval(timer)
  }, [onLoggedIn, t])

  return (
    <main className="card">
      <h1>{t('app.name')}</h1>
      <p>{t('auth.prompt')}</p>
      <div ref={buttonRef} />
      {error && <p className="error">{error}</p>}
    </main>
  )
}
