import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'
import UserMenu, { useDismissable } from './UserMenu'

const SECTIONS = [
  { to: '/schedule', key: 'schedule', needs: 'classes' },
  { to: '/plan', key: 'plan', needs: 'classes' },
  // раздел методиста: роль не иерархическая, у большинства назначений нет,
  // и пустой раздел в баре был бы обещанием работы, которой нет
  { to: '/reviews', key: 'reviews', needs: null, methodistOnly: true },
  { to: '/classes', key: 'classes', needs: 'year' },
  { to: '/year', key: 'year', needs: null },
  // the school section exists only for its administrators; a teacher has
  // nothing to do there and the server would refuse anyway
  { to: '/school', key: 'school', needs: null, adminOnly: true },
  // the only place a Django superuser is visible in the ordinary interface
  { to: '/schools', key: 'schools', needs: null, superuserOnly: true },
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

export default function NavBar({
  user,
  status,
  reviews = 0,
  onLoggedOut,
  onLanguageChange,
}) {
  const { t } = useTranslation()
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const menuRef = useDismissable(menuOpen, closeMenu)

  // following a link closes the burger
  useEffect(() => setMenuOpen(false), [location.pathname])

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
            (section) =>
              (!section.adminOnly || user?.is_school_admin) &&
              (!section.superuserOnly || user?.is_superuser) &&
              (!section.methodistOnly || user?.methodist_courses?.length),
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
                {section.key === 'reviews' && reviews > 0 && (
                  <span className="nav-count">{reviews}</span>
                )}
              </NavLink>
            )
          })}
        </nav>

        <UserMenu
          user={user}
          profileTo="/profile"
          onLoggedOut={onLoggedOut}
          onLanguageChange={onLanguageChange}
        />
      </div>
    </header>
  )
}
