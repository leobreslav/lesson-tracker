import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import EmptyState from './EmptyState'
import ErrorBoundary from './ErrorBoundary'
import UserMenu from './UserMenu'
import { fetchStudentCourses } from './api'

/**
 * Интерфейс ученика — отдельная ветка, а не роль внутри учительской.
 *
 * Ветвление стоит выше роутера и выше фоновых запросов: у учителя на каждую
 * навигацию уходят `/api/onboarding/status/` и `/api/plan/reviews/`, и
 * ученику они ответят отказом. Дешевле не звать их вовсе, чем учить каждый
 * из них молчать.
 *
 * Разделов у ученика пока один — свои курсы. Бар всё равно свой: учительский
 * состоит из пунктов, которых у него нет, и общего в них только правый угол
 * (`UserMenu`), который и вынесен.
 *
 * Профиля у ученика нет: имя приходит из Google, язык переключается прямо в
 * меню, а больше в профиле учителя ничего и нет.
 */
export default function StudentApp({ user, onLoggedOut, onLanguageChange }) {
  const { t } = useTranslation()

  return (
    <BrowserRouter>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            {t('app.name')}
          </Link>
          <UserMenu
            user={user}
            onLoggedOut={onLoggedOut}
            onLanguageChange={onLanguageChange}
          />
        </div>
      </header>

      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<StudentCourses onLoggedOut={onLoggedOut} />} />
          <Route path="*" element={<StudentNotFound />} />
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  )
}

/**
 * Свои курсы: где учусь и где учился.
 *
 * Два списка, а не один. Снятый с курса продолжает видеть, что уже сделал, —
 * и должен понимать, почему курс уехал вниз: курс, исчезнувший без
 * объяснения, читается как поломка.
 */
function StudentCourses({ onLoggedOut }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState(null)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    let cancelled = false

    fetchStudentCourses()
      .then((result) => !cancelled && setCourses(result.courses))
      .catch((err) => !cancelled && handleError(err))

    return () => {
      cancelled = true
    }
  }, [handleError])

  if (courses === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const active = courses.filter((course) => course.active)
  const past = courses.filter((course) => !course.active)

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('student.title')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!courses.length ? (
        <EmptyState title={t('student.empty.title')}>
          {t('student.empty.hint')}
        </EmptyState>
      ) : !active.length ? (
        // курсы были, но все сняты: про настоящее надо сказать словами,
        // иначе страница молчит о том, что сейчас делать нечего
        <p className="hint">{t('student.noActive')}</p>
      ) : (
        <ul className="class-list student-courses">
          {active.map((course) => (
            <li key={course.id}>
              <span className="name">{course.name}</span>
              <span className="hint">{describe(course, t)}</span>
            </li>
          ))}
        </ul>
      )}

      {past.length > 0 && (
        <section className="panel">
          <h3>{t('student.past.title')}</h3>
          <p className="hint">{t('student.past.hint')}</p>
          <ul className="class-list student-courses past">
            {past.map((course) => (
              <li key={course.id}>
                <span className="name">{course.name}</span>
                <span className="hint">{describe(course, t)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}

/** «Предмет · параллель», без пустых разделителей. */
function describe(course, t) {
  return [course.subject, course.grade].filter(Boolean).join(' · ') || t('student.noSubject')
}

function StudentNotFound() {
  const { t } = useTranslation()

  return (
    <main className="page narrow">
      <header className="page-header">
        <h1>{t('notFound.title')}</h1>
      </header>
      <p className="hint">{t('notFound.hint')}</p>
      <p>
        <Link to="/">{t('student.title')}</Link>
      </p>
    </main>
  )
}
