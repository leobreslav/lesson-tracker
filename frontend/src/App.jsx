import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'
import Agenda from './Agenda'
import Calendar from './Calendar'
import Classes from './Classes'
import Dashboard from './Dashboard'
import Reviews from './Reviews'
import Login from './Login'
import NavBar from './NavBar'
import NoSchool from './NoSchool'
import NotFound from './NotFound'
import Plan from './Plan'
import Profile from './Profile'
import School from './School'
import StudentApp from './StudentApp'
import SchoolCourses from './SchoolCourses'
import SchoolOverview from './SchoolOverview'
import SchoolReference from './SchoolReference'
import SchoolStudents from './SchoolStudents'
import Works from './Works'
import SchoolTeachers from './SchoolTeachers'
import SchoolSchedule from './SchoolSchedule'
import Schools from './Schools'
import {
  clearToken,
  fetchMe,
  fetchOnboarding,
  fetchReviews,
  getToken,
  updateMe,
} from './api'
import i18n, { normalizeLanguage } from './i18n'

export default function App() {
  const [token, setTokenState] = useState(getToken)
  // the name for the bar: pages fetch their own data themselves
  const [user, setUser] = useState(null)
  // what is filled in already: the main page builds steps out of it and the
  // bar dims the sections that are not usable yet
  const [status, setStatus] = useState(null)
  const [reviews, setReviews] = useState(0)

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

  // Пока неизвестно, кто вошёл, не рисуем ничего.
  //
  // Раньше учительская оболочка появлялась сразу, а имя доезжало следом —
  // мелкая любезность, которая со вторым видом пользователя стала ошибкой:
  // ученик на долю секунды получал учительский экран, и тот успевал сходить
  // за шагами первого входа и получить 403. Один запрос `/api/me/` того не
  // стоит.
  if (!user) {
    return (
      <main className="page">
        <p>{i18n.t('common.loading')}</p>
      </main>
    )
  }

  // ученик — другое приложение целиком, и ветка стоит **выше** роутера и
  // фоновых наблюдателей: на каждую навигацию они спрашивают шаги первого
  // входа и очередь методиста, а ученику оба ответят отказом. Дешевле не
  // звать их вовсе, чем учить каждый молчать
  if (user.kind === 'student') {
    return (
      <StudentApp
        user={user}
        onLoggedOut={handleLoggedOut}
        onLanguageChange={handleLanguageChange}
      />
    )
  }

  // signed in but invited by nobody: every section would answer 403, so one
  // honest screen replaces five identical refusals. A superuser is the
  // exception — they are the one who creates the schools, and locking them
  // out of that screen is how an installation ends up with no way in.
  if (!user.school && !user.is_superuser) {
    return <NoSchool user={user} onLoggedOut={handleLoggedOut} />
  }

  const guarded = (Page, props) => <Page onLoggedOut={handleLoggedOut} {...props} />

  return (
    <BrowserRouter>
      <NavBar
        user={user}
        status={status}
        reviews={reviews}
        onLoggedOut={handleLoggedOut}
        onLanguageChange={handleLanguageChange}
      />
      <StatusWatcher onChange={setStatus} />
      {/* счётчик в баре: методист должен видеть, что его ждут, не заходя
          в раздел. Писем пока нет, и это единственное уведомление */}
      {user?.methodist_courses?.length > 0 && (
        <ReviewWatcher onChange={setReviews} />
      )}

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
          <Route path="/reviews" element={guarded(Reviews)} />
          <Route path="/plan" element={guarded(Plan)} />
          <Route path="/works" element={guarded(Works)} />
          <Route path="/classes" element={guarded(Classes, { user })} />
          {/* «Школа» — не одна страница, а четыре: рамка с подменю и
              вложенные маршруты под ней */}
          <Route
            path="/school"
            element={guarded(School, {
              user,
              onSchoolChange: (school) =>
                setUser((prev) => (prev ? { ...prev, school } : prev)),
            })}
          >
            <Route index element={<SchoolOverview />} />
            <Route path="teachers" element={<SchoolTeachers />} />
            <Route path="courses" element={<SchoolCourses />} />
            <Route path="students" element={<SchoolStudents />} />
            <Route path="reference" element={<SchoolReference />} />
          </Route>
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
function ReviewWatcher({ onChange }) {
  const location = useLocation()

  useEffect(() => {
    let cancelled = false

    fetchReviews()
      .then(
        (data) =>
          !cancelled &&
          onChange(
            data.plans.filter((plan) => plan.review?.status === 'pending').length,
          ),
      )
      .catch(() => {
        // не ответили — счётчика просто не будет
      })

    return () => {
      cancelled = true
    }
  }, [location.pathname, onChange])

  return null
}

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
