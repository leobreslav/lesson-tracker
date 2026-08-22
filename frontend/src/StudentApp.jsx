import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import EmptyState from './EmptyState'
import FeedbackButton from './FeedbackButton'
import ErrorBoundary from './ErrorBoundary'
import StudentCourse from './StudentCourse'
import StudentWork from './StudentWork'
import UserMenu from './UserMenu'
import { fetchStudentCourses, fetchStudentWorks } from './api'
import { dateTime } from './dates'

/**
 * Интерфейс ученика — отдельная ветка, а не роль внутри учительской.
 *
 * Ветвление стоит выше роутера и выше фоновых запросов: у учителя на каждую
 * навигацию уходят `/api/onboarding/status/` и `/api/plan/reviews/`, и
 * ученику они ответят отказом. Дешевле не звать их вовсе, чем учить каждый
 * из них молчать.
 *
 * Разделов у ученика два — список курсов и курс целиком. Бар всё равно свой:
 * учительский
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
          {/* та же кнопка, что у учителя: поломку ученик видит ту же, а
              сказать о ней ему было нечем — администратор школы интерфейс
              не чинит */}
          <FeedbackButton compact />

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
          <Route
            path="/courses/:id"
            element={<StudentCourse onLoggedOut={onLoggedOut} />}
          />
          <Route path="/works/:id" element={<StudentWork />} />
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
 *
 * Название курса ведёт на его страницу — там учебный план и все работы. А
 * здесь под ним остаются только **открытые** работы: этот экран отвечает на
 * вопрос «что делать сейчас», и закрытые в нём были бы архивом поверх
 * ответа. Архив живёт на странице курса, одним нажатием ниже.
 */
function StudentCourses({ onLoggedOut }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState(null)
  const [works, setWorks] = useState([])
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

    // курсы и работы одним заходом: экран без второго — половина ответа на
    // вопрос «что мне делать», а два состояния загрузки подряд мигают
    Promise.all([fetchStudentCourses(), fetchStudentWorks()])
      .then(([mine, assigned]) => {
        if (cancelled) return
        setCourses(mine.courses)
        setWorks(assigned.works)
      })
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
              <Link className="name" to={`/courses/${course.id}`}>
                {course.name}
              </Link>
              <span className="hint">{describe(course, t)}</span>
              <WorkList works={openIn(works, course)} />
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
                <Link className="name" to={`/courses/${course.id}`}>
                  {course.name}
                </Link>
                <span className="hint">{describe(course, t)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}

/** Открытые работы курса: то, за что можно взяться прямо сейчас. */
const openIn = (works, course) =>
  works.filter((work) => work.course_id === course.id && work.state === 'open')

/**
 * Открытые работы под названием курса.
 *
 * Ненаступивших здесь не бывает вовсе: до открытия окна работы для ученика
 * не существует. Закрытые есть, но не здесь — они на странице курса, вместе
 * с планом: свои ответы и отметки он читает всегда, и это ровно то, ради
 * чего строка зачисления не удаляется.
 */
function WorkList({ works }) {
  const { t } = useTranslation()

  if (!works.length) return null

  return (
    <ul className="work-links">
      {works.map((work) => (
        <li key={work.id}>
          <Link to={`/works/${work.id}`}>{work.title}</Link>
          <span className={`badge state-${work.state}`}>
            {t(`works.state.${work.state}`)}
          </span>
          <span className="hint">
            {t('student.work.progress', {
              answered: work.answered,
              tasks: work.tasks,
            })}
          </span>
          <span className="hint">
            {t(work.state === 'open' ? 'student.work.until' : 'student.work.was', {
              moment: dateTime(work.closes_at),
            })}
          </span>
        </li>
      ))}
    </ul>
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
