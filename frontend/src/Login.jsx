import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { loginWithGoogle, requestLoginCode, setToken, verifyLoginCode } from './api'
import i18n, { browserLanguage } from './i18n'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

/**
 * Вход по коду из письма — вторая дверь, под кнопкой Google.
 *
 * Для тех, у кого нет Google-аккаунта на адресе, который записала школа:
 * родителей импорт заводит по адресу из ManageBac, и часть из них входит в
 * ManageBac паролем. Две ступени: адрес → письмо с кодом → код → токен той
 * же формы, что у Google, и дальше приложение не различает, откуда он.
 *
 * Ответ на адрес одинаков для любого адреса — сервер не говорит, кто в
 * школе, — поэтому после отправки экран говорит «если адрес нам известен,
 * письмо ушло», а не «письмо ушло».
 */
function CodeLogin({ onLoggedIn, onError }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  const send = async (event) => {
    event.preventDefault()
    setBusy(true)
    onError(null)
    try {
      await requestLoginCode(email.trim())
      setSent(true)
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const verify = async (event) => {
    event.preventDefault()
    setBusy(true)
    onError(null)
    try {
      const { key } = await verifyLoginCode(email.trim(), code.trim())
      setToken(key)
      onLoggedIn()
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <p className="code-login">
        <button type="button" className="link" onClick={() => setOpen(true)}>
          {t('auth.code.open')}
        </button>
      </p>
    )
  }

  return (
    <form className="code-login" onSubmit={sent ? verify : send}>
      <div className="field">
        <label htmlFor="login-email">{t('auth.code.email')}</label>
        <input
          id="login-email"
          type="email"
          value={email}
          required
          autoFocus
          disabled={busy || sent}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      {sent && (
        <>
          <p className="hint">{t('auth.code.sent')}</p>
          <div className="field">
            <label htmlFor="login-code">{t('auth.code.code')}</label>
            <input
              id="login-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              value={code}
              required
              autoFocus
              disabled={busy}
              onChange={(event) => setCode(event.target.value)}
            />
          </div>
        </>
      )}
      <div className="row">
        <button type="submit" disabled={busy || !email.trim() || (sent && code.trim().length < 6)}>
          {sent ? t('auth.code.signIn') : t('auth.code.send')}
        </button>
        {sent && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              setSent(false)
              setCode('')
            }}
          >
            {t('auth.code.again')}
          </button>
        )}
      </div>
    </form>
  )
}

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
      <CodeLogin onLoggedIn={onLoggedIn} onError={setError} />
      {error && <p className="error">{error}</p>}
    </main>
  )
}
