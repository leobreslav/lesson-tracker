import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { logout } from './api'
import { LANGUAGES } from './i18n'

const SECTIONS = [
  { to: '/schedule', key: 'schedule', needs: 'classes' },
  { to: '/layout', key: 'layout', needs: 'classes' },
  { to: '/plan', key: 'plan', needs: 'classes' },
  { to: '/classes', key: 'classes', needs: 'year' },
  { to: '/year', key: 'year', needs: null },
  // the school section exists only for its administrators; a teacher has
  // nothing to do there and the server would refuse anyway
  { to: '/school', key: 'school', needs: null, adminOnly: true },
]

/**
 * Why a section is not usable yet, as a translation key.
 *
 * The item still navigates: forbidding the click buys nothing, the page
 * explains what is missing. Dimming is a hint, not a barrier.
 */
function reasonKeyFor(needs, status) {
  if (!status || !needs) return null
  if (!status.year.exists) return 'nav.needYear'
  if (needs === 'classes' && !status.classes.count) return 'nav.needClass'
  return null
}

/** Closing on an outside click and on Escape — shared by both bar menus. */
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

export default function NavBar({ user, status, onLoggedOut, onLanguageChange }) {
  const { t, i18n } = useTranslation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const location = useLocation()

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const closeUser = useCallback(() => setUserOpen(false), [])

  const menuRef = useDismissable(menuOpen, closeMenu)
  const userRef = useDismissable(userOpen, closeUser)

  // following a link closes both the burger and the user menu
  useEffect(() => {
    setMenuOpen(false)
    setUserOpen(false)
  }, [location.pathname])

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      onLoggedOut()
    }
  }

  const name = user
    ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email
    : '…'

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link to="/" className="brand">
          {t('app.name')}
        </Link>

        <button
          type="button"
          className="burger secondary"
          aria-label={t('nav.menu')}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          ☰
        </button>

        <nav
          ref={menuRef}
          className={menuOpen ? 'topbar-nav open' : 'topbar-nav'}
        >
          {SECTIONS.filter(
            (section) => !section.adminOnly || user?.is_school_admin,
          ).map((section) => {
            const reasonKey = reasonKeyFor(section.needs, status)
            const reason = reasonKey ? t(reasonKey) : null

            return (
              <NavLink
                key={section.to}
                to={section.to}
                title={reason ?? undefined}
                className={({ isActive }) =>
                  'nav-link' +
                  (isActive ? ' active' : '') +
                  (reason ? ' unavailable' : '')
                }
              >
                {t(`nav.${section.key}`)}
              </NavLink>
            )
          })}
        </nav>

        <div className="user-menu" ref={userRef}>
          <button
            type="button"
            className="secondary"
            aria-haspopup="menu"
            aria-expanded={userOpen}
            onClick={() => setUserOpen((open) => !open)}
          >
            {name} ▾
          </button>

          {userOpen && (
            <ul className="dropdown" role="menu">
              <li role="none">
                <Link role="menuitem" to="/profile">
                  {t('nav.profile')}
                </Link>
              </li>
              <li className="dropdown-languages" role="none">
                <span className="hint">{t('language.label')}</span>
                <div className="actions">
                  {LANGUAGES.map((language) => (
                    <button
                      key={language.code}
                      type="button"
                      role="menuitem"
                      className={
                        language.code === i18n.language ? 'chip active' : 'chip'
                      }
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
      </div>
    </header>
  )
}
