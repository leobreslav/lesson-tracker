import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { logout } from './api'
import { LANGUAGES } from './i18n'

/**
 * Меню пользователя в правом углу бара — одно на оба интерфейса.
 *
 * У учителя и ученика бары разные: разделы у них общего не имеют, и один
 * компонент с флагом «а этому не показывай» получился бы длиннее двух. А вот
 * правый угол одинаков — имя, адрес, язык, выход, — и второй его копии быть
 * не должно: язык переключается в одном месте, выход тоже.
 *
 * Профиль в списке есть только у того, у кого он есть: `profileTo` пустой —
 * пункт не рисуется.
 */

/** Закрытие по клику мимо и по Escape. */
function useDismissable(open, close) {
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined

    const onPointerDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) close()
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') close()
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, close])

  return ref
}

export { useDismissable }

export default function UserMenu({ user, profileTo = null, onLoggedOut, onLanguageChange }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const close = useCallback(() => setOpen(false), [])
  const ref = useDismissable(open, close)

  // переход по ссылке закрывает меню
  useEffect(() => setOpen(false), [location.pathname])

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      onLoggedOut()
    }
  }

  // имя и адрес — две строки одной кнопки: под именем в школе ходят тёзки,
  // а входят все через Google, и адрес — единственное, чем один «Иванов»
  // отличается от другого. Имени нет — остаётся адрес, и второй раз его
  // повторять незачем
  const name = user
    ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
    : '…'
  const email = user && name !== user.email ? user.email : null

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="secondary"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="who">
          <span className="name">{name}</span>
          {email && <span className="email">{email}</span>}
        </span>
        <span aria-hidden="true">▾</span>
      </button>

      {open && (
        <ul className="dropdown" role="menu">
          {profileTo && (
            <li role="none">
              <Link role="menuitem" to={profileTo}>
                {t('nav.profile')}
              </Link>
            </li>
          )}
          <li className="dropdown-languages" role="none">
            <span className="hint">{t('language.label')}</span>
            <div className="actions">
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  type="button"
                  role="menuitem"
                  className={language.code === i18n.language ? 'chip active' : 'chip'}
                  onClick={() => onLanguageChange(language.code)}
                >
                  {language.label}
                </button>
              ))}
            </div>
          </li>
          <li role="none">
            <button type="button" role="menuitem" onClick={handleLogout}>
              {t('nav.logout')}
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}
