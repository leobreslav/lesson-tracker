import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'
import FeedbackButton from './FeedbackButton'
import UserMenu, { useDismissable } from './UserMenu'

const SECTIONS = [
  // расписание первым и оно же корень: с него заходят в занятие, а
  // «как идут курсы» смотрят раз в неделю.
  //
  // Гаснет оно **только без календаря**, и это не мелочь: пустое
  // расписание — законный повод зайти (человек идёт ставить в него часы),
  // а приглушённый пункт читается как «сюда пока нельзя». Без учебного
  // года расписания не создать вовсе — там гасить честно
  { to: '/schedule', key: 'schedule', needs: 'year' },
  { to: '/plan', key: 'plan', needs: 'classes' },
  { to: '/works', key: 'works', needs: 'classes' },
  // задачник ни от чего не зависит: библиотека читается и без курсов
  { to: '/bank', key: 'bank', needs: null },
  // «Курсы» и «Учебный год» из бара убраны: оба живут в разделе «Школа»,
  // где их и правят, а учителю список курсов и так виден чипами на своих
  // страницах — расписании, плане и работах
  // the school section exists only for its administrators; a teacher has
  // nothing to do there and the server would refuse anyway
  { to: '/school', key: 'school', needs: null, adminOnly: true },
  // the only place a Django superuser is visible in the ordinary interface
  { to: '/schools', key: 'schools', needs: null, superuserOnly: true },
  // и второй его раздел: обращения пользователей копятся здесь
  { to: '/feedback', key: 'feedback', needs: null, superuserOnly: true },
]

/**
 * Why a section is not usable yet, as a translation key.
 *
 * The item still navigates: forbidding the click buys nothing, the page
 * explains what is missing. Dimming is a hint, not a barrier.
 *
 * Уровня два, и разница между ними содержательная. `year` — без учебного
 * года раздела **не существует**: ни расписания, ни плана не построить.
 * `classes` — курсов нет, то есть работать не с чем. Расписанию хватает
 * первого: пустая сетка это приглашение поставить в неё часы, а не
 * состояние «сюда пока нельзя».
 */
function reasonKeyFor(needs, status) {
  if (!status || !needs) return null
  if (!status.year.exists) return 'nav.needYear'
  if (needs === 'classes' && !status.classes.count) return 'nav.needClass'
  return null
}

export default function NavBar({ user, status, onLoggedOut, onLanguageChange }) {
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
              (!section.superuserOnly || user?.is_superuser),
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

        {/* правый угол — пара: «Написать» и меню пользователя. Сказать
            разработчику стоит рядом с именем, а не пунктом внутри меню: о
            поломке говорят в тот момент, когда её увидели, и искать её под
            своим именем никто не станет */}
        <div className="topbar-right">
          <FeedbackButton />

          <UserMenu
            user={user}
            profileTo="/profile"
            onLoggedOut={onLoggedOut}
            onLanguageChange={onLanguageChange}
          />
        </div>
      </div>
    </header>
  )
}
