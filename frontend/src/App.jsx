import { useCallback, useEffect, useState } from 'react'
import Bank from './Bank'
import BankProblem from './BankProblem'
import BankChronology from './BankChronology'
import BankSearch from './BankSearch'
import Proposals from './Proposals'
import StudentTrack from './StudentTrack'
import BankTopics from './BankTopics'
import BankSource from './BankSource'
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'
import LessonScreen from './LessonScreen'
import Calendar from './Calendar'
import Login from './Login'
import NavBar from './NavBar'
import NoSchool from './NoSchool'
import NotFound from './NotFound'
import Plan from './Plan'
import Profile from './Profile'
import Schedule from './Schedule'
import School from './School'
import ParentApp from './ParentApp'
import StudentApp from './StudentApp'
import { forgetViewedChild } from './viewedChild'
import SchoolCourses from './SchoolCourses'
import SchoolOverview from './SchoolOverview'
import SchoolReference from './SchoolReference'
import SchoolStudents from './SchoolStudents'
import Works from './Works'
import WorkEdit from './WorkEdit'
import WorkTable from './WorkTable'
import SchoolTeachers from './SchoolTeachers'
import StartHere, { hasSteps } from './StartHere'
import Feedback from './Feedback'
import Schools from './Schools'
import {
  clearToken,
  fetchMe,
  fetchOnboarding,
  getToken,
  updateMe,
} from './api'
import { useTranslation } from 'react-i18next'
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
    // выбранный ребёнок — про вышедшего, а не про браузер: следующий
    // вошедший на этой машине не должен унаследовать чужого, и запрос с
    // чужим номером ответил бы ему `not_your_child` на каждом экране
    forgetViewedChild()
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

  // родитель — третья ветка по той же причине, что ученик: учительские
  // наблюдатели ему ответят отказом. Экраны про учёбу он берёт у ученика
  // целиком, отличается только «про кого» (`viewedChild`), — но ветка нужна
  // всё равно: у него свой бар с выбором ребёнка и свой раздел переписки
  if (user.kind === 'parent') {
    return (
      <ParentApp
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
        onLoggedOut={handleLoggedOut}
        onLanguageChange={handleLanguageChange}
      />
      <StatusWatcher onChange={setStatus} />

      <PageBoundary>
        <Routes>
          {/*
            Корень — шаги первого входа, пока есть что настраивать.

            Стояли они прямо в «Моём расписании», потому что корень вёл
            туда же. Но расписание открывают каждый день и ради сетки, а
            карта первого входа отвечает на вопрос, который задают один
            раз: полтора экрана поверх рабочей страницы читались как
            реклама. Настраивать нечего — корень по-прежнему уводит на
            расписание, и никакой лишней страницы не появляется.
          */}
          <Route
            path="/"
            element={guarded(StartPage, { status, onStatusChange: setStatus })}
          />
          {/* работа с одним уроком: прошлым, сегодняшним или будущим —
              заходят сюда одинаково, разница лишь в том, какие действия
              имеют смысл */}
          <Route path="/lesson/:id" element={guarded(LessonScreen)} />
          {/* раздела «Мои курсы» больше нет: числа в нём дублировали план,
              долги переехали в его таблицу, надзор методиста — в селектор
              курса, а шаги первого входа сюда, на корень */}
          <Route path="/schedule" element={guarded(Schedule, { user })} />
          {/* роль нужна самой странице: администратору она показывает
              курсы школы отдельной группой селектора */}
          <Route path="/plan" element={guarded(Plan, { user })} />
          <Route path="/works" element={guarded(Works)} />
          <Route path="/works/:id" element={guarded(WorkTable)} />
          {/* два адреса у одной работы, и названы они по тому, что на них
              делают: `/works/:id` — как справились, `/works/:id/edit` — из
              чего работа состоит. Правка стояла окном и в него не влезала */}
          <Route path="/works/:id/edit" element={guarded(WorkEdit)} />
          <Route path="/bank" element={guarded(Bank)} />
          <Route path="/track/:id" element={guarded(StudentTrack)} />
          <Route path="/bank/proposals" element={guarded(Proposals)} />
          <Route path="/bank/topics" element={guarded(BankTopics)} />
          <Route path="/bank/chronology" element={guarded(BankChronology)} />
          <Route path="/bank/search" element={guarded(BankSearch)} />
          <Route path="/bank/source/:id" element={guarded(BankSource)} />
          <Route path="/bank/problem/:id" element={guarded(BankProblem)} />
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
          {/* всё, что написали пользователи: второй раздел суперпользователя.
              Права проверяет сервер — вьюха отвечает 403 всем остальным */}
          <Route
            path="/feedback"
            element={guarded(Feedback, { user, onSaved: setUser })}
          />
          {/* адрес остался жив: на него ведут ссылки из раздела «Школа» и
              закладки, а страница расписания теперь одна на оба вида */}
          <Route
            path="/school/schedule"
            element={<Navigate to="/schedule?view=school" replace />}
          />
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
/**
 * Корень: карта первого входа, пока она что-то говорит.
 *
 * Своей страницы у шагов не было — они стояли поверх расписания, — и это
 * ровно то, за что их и невзлюбили: расписание открывают ради сетки, а не
 * ради инструкции. Когда настраивать нечего, страницы не существует:
 * корень уводит на расписание, как уводил всегда.
 *
 * Пока статус не приехал, не решаем ничего: редирект по недозагруженному
 * ответу увёл бы с шагов того, кому они как раз нужны.
 */
function StartPage({ status, onStatusChange, onLoggedOut }) {
  const { t } = useTranslation()

  if (status === null) return null
  if (!hasSteps(status)) return <Navigate to="/schedule" replace />

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('dashboard.startTitle')}</h1>
      </header>
      <StartHere
        status={status}
        onStatusChange={onStatusChange}
        onLoggedOut={onLoggedOut}
      />
    </main>
  )
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
