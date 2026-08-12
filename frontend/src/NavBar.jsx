import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { logout } from './api'

const SECTIONS = [
  { to: '/schedule', label: 'Моё расписание' },
  { to: '/layout', label: 'Раскладка' },
  { to: '/plan', label: 'Учебный план' },
  { to: '/classes', label: 'Классы' },
  { to: '/year', label: 'Учебный год' },
]

/** Закрытие по клику мимо и по Escape — общее для обоих меню бара. */
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

export default function NavBar({ user, onLoggedOut }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const location = useLocation()

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const closeUser = useCallback(() => setUserOpen(false), [])

  const menuRef = useDismissable(menuOpen, closeMenu)
  const userRef = useDismissable(userOpen, closeUser)

  // переход по пункту закрывает и гамбургер, и меню пользователя
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
          Трекер уроков
        </Link>

        <button
          type="button"
          className="burger secondary"
          aria-label="Меню разделов"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          ☰
        </button>

        <nav
          ref={menuRef}
          className={menuOpen ? 'topbar-nav open' : 'topbar-nav'}
        >
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              {section.label}
            </NavLink>
          ))}
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
                  Профиль
                </Link>
              </li>
              <li role="none">
                <button type="button" role="menuitem" onClick={handleLogout}>
                  Выйти
                </button>
              </li>
            </ul>
          )}
        </div>
      </div>
    </header>
  )
}
