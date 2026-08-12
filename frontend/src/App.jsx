import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'
import Agenda from './Agenda'
import Calendar from './Calendar'
import Classes from './Classes'
import Dashboard from './Dashboard'
import Layout from './Layout'
import Library from './Library'
import Login from './Login'
import NavBar from './NavBar'
import NoSchool from './NoSchool'
import NotFound from './NotFound'
import Plan from './Plan'
import Profile from './Profile'
import School from './School'
import SchoolSchedule from './SchoolSchedule'
import Schools from './Schools'
import { clearToken, fetchMe, fetchOnboarding, getToken, updateMe } from './api'
import i18n, { normalizeLanguage } from './i18n'

export default function App() {
  const [token, setTokenState] = useState(getToken)
  // the name for the bar: pages fetch their own data themselves
  const [user, setUser] = useState(null)
  // what is filled in already: the main page builds steps out of it and the
  // bar dims the sections that are not usable yet
  const [status, setStatus] = useState(null)

  const handleLoggedIn = useCallback(() => setTokenState(getToken()), [])

  /**
   * Switching the language applies at once and is saved to the profile.
   *
   * The interface must not wait for the request: a failed save is not worth
   * bouncing the language back, the next sign-in will simply read the old one.
   */
  const handleLanguageChange = useCallback((code) => {
    const language = normalizeLanguage(code)
    i18n.changeLanguage(language)
    setUser((prev) => (prev ? { ...prev, language } : prev))
    updateMe({ language }).catch(() => {})
  }, [])

  const handleLoggedOut = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
    setStatus(null)
    window.google?.accounts?.id?.disableAutoSelect()
  }, [])

  useEffect(() => {
    if (!token) return undefined

    let cancelled = false
    fetchMe()
      .then((data) => {
        if (cancelled) return
        setUser(data)
        // the profile is the source of truth for the language: the same
        // account reads the same way on any device
        i18n.changeLanguage(normalizeLanguage(data.language))
      })
      .catch((err) => {
        // the token has expired — back to the login page
        if (err.status === 401) handleLoggedOut()
      })

    return () => {
      cancelled = true
    }
  }, [token, handleLoggedOut])

  // no bar on the login page: there is nothing and nobody to show it to
  if (!token) return <Login onLoggedIn={handleLoggedIn} />

  // signed in but invited by nobody: every section would answer 403, so one
  // honest screen replaces five identical refusals. A superuser is the
  // exception — they are the one who creates the schools, and locking them
  // out of that screen is how an installation ends up with no way in.
  if (user && !user.school && !user.is_superuser) {
    return <NoSchool user={user} onLoggedOut={handleLoggedOut} />
  }

  const guarded = (Page, props) => <Page onLoggedOut={handleLoggedOut} {...props} />

  return (
    <BrowserRouter>
      <NavBar
        user={user}
        status={status}
        onLoggedOut={handleLoggedOut}
        onLanguageChange={handleLanguageChange}
      />
      <StatusWatcher onChange={setStatus} />

      <PageBoundary>
        <Routes>
          <Route
            path="/"
            element={
              <Dashboard
                user={user}
                status={status}
                onStatusChange={setStatus}
                onLoggedOut={handleLoggedOut}
              />
            }
          />
          <Route path="/schedule" element={guarded(Agenda)} />
          <Route path="/layout" element={guarded(Layout)} />
          <Route path="/plan" element={guarded(Plan)} />
          <Route path="/library" element={guarded(Library)} />
          <Route path="/classes" element={guarded(Classes, { user })} />
          <Route
            path="/school"
            element={guarded(School, {
              user,
              onSchoolChange: (school) =>
                setUser((prev) => (prev ? { ...prev, school } : prev)),
            })}
          />
          <Route path="/schools" element={guarded(Schools, { user })} />
          <Route path="/school/schedule" element={guarded(SchoolSchedule)} />
          <Route path="/year" element={guarded(Calendar, { user })} />
          <Route path="/profile" element={guarded(Profile, { onSaved: setUser })} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </PageBoundary>
    </BrowserRouter>
  )
}

/**
 * The onboarding status is re-read on every navigation: data changes on other
 * pages, and the bar and the main page have to tell the truth. The request is
 * small — a dedicated sync mechanism would cost more than it saves.
 */
function StatusWatcher({ onChange }) {
  const location = useLocation()

  useEffect(() => {
    let cancelled = false

    fetchOnboarding()
      .then((data) => {
        if (!cancelled) onChange(data)
      })
      .catch(() => {
        // no answer — the bar simply dims nothing
      })

    return () => {
      cancelled = true
    }
  }, [location.pathname, onChange])

  return null
}

/**
 * A trap around the page content. The bar lives outside it, so after a crash
 * another section is still reachable; changing the address resets the trap
 * through its key.
 */
function PageBoundary({ children }) {
  const location = useLocation()
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>
}
