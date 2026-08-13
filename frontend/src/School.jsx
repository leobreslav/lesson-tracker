import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useOutletContext } from 'react-router-dom'

const TABS = [
  { to: '/school', key: 'overview', end: true },
  { to: '/school/teachers', key: 'teachers' },
  { to: '/school/courses', key: 'courses' },
  { to: '/school/reference', key: 'reference' },
]

/**
 * The administrator's section, split into four.
 *
 * It used to be one page holding the school's name, its courses, its people,
 * its invitations and a form for adding subjects — everything the school
 * owns, in one column. Four different jobs were interleaved there, and the
 * one that matters most (who teaches what) had nowhere to live at all.
 *
 * This is only the frame: the tabs and whatever the route below them renders.
 */
export default function School({ user, onLoggedOut, onSchoolChange }) {
  const { t } = useTranslation()

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('school.title', { name: user?.school?.name ?? '' })}</h1>
      </header>

      <nav className="subnav">
        {TABS.map((tab) => (
          <NavLink key={tab.key} to={tab.to} end={tab.end}>
            {t(`school.tabs.${tab.key}`)}
          </NavLink>
        ))}
      </nav>

      <Outlet context={{ user, onLoggedOut, onSchoolChange }} />
    </main>
  )
}

/** The frame's context, so every tab reads it the same way. */
export function useSchoolSection() {
  return useOutletContext()
}
