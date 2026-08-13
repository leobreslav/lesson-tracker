import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import { fetchProgress } from './api'
import { longDate, shortDate, shortWeekday } from './dates'

/**
 * «Раскладка» — экран текущего состояния, а не список уроков.
 *
 * Ленту с датами забрал себе учебный план: там она рабочая, там же её и
 * правят. Здесь остаётся то, чего в плане нет и не должно быть: где курс
 * идёт сейчас, успевает ли, что впереди и как разложился год по четвертям —
 * и всё это **сразу по всем курсам**. План всегда про один курс, раскладка
 * про все: учитель ведёт пять и хочет одним взглядом понять, где проблема.
 *
 * Числа приходят одним запросом `/api/plan/progress/`, который считает их
 * тем же `build_layout`, что и остальные ответы про раскладку. Своих
 * расчётов на странице нет вовсе — иначе они однажды разошлись бы с планом.
 */
export default function Layout({ onLoggedOut }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [courses, setCourses] = useState(null)
  const [opened, setOpened] = useState(null)
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

    fetchProgress()
      .then((result) => {
        if (cancelled) return
        setCourses(result.courses)
        // один курс разворачиваем сразу: прятать за нажатием нечего
        if (result.courses.length === 1) setOpened(result.courses[0].id)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  /** «Опережаете на 2» / «отстаёте на 3» / «идёте вровень». */
  const paceText = (course) => {
    if (!course.slots_total || !course.lessons_total) return t('layout.pace.idle')
    if (course.pace === 0) return t('layout.pace.even')
    return t(course.pace > 0 ? 'layout.pace.ahead' : 'layout.pace.behind', {
      count: Math.abs(course.pace),
    })
  }

  const paceClass = (course) => {
    if (!course.slots_total || !course.lessons_total || course.pace === 0) return ''
    return course.pace > 0 ? ' good' : ' bad'
  }

  /** «урок 14 из 44 · Одночлены и многочлены». */
  const whereText = (course) => {
    if (!course.lessons_total) return t('layout.where.noPlan')
    if (!course.current) return t('layout.where.finished', { count: course.done })

    return [
      t('layout.where.at', {
        number: course.current.number,
        total: course.lessons_total,
      }),
      course.current.section_title,
    ]
      .filter(Boolean)
      .join(' · ')
  }

  const balanceText = (balance) => `${balance > 0 ? '+' : ''}${balance}`

  const details = (course) => (
    <div className="progress-details">
      <div className="cards">
        <section className="panel card-stat" data-card="done">
          <h2>
            {course.done} / {course.lessons_total}
          </h2>
          <p className="hint">{t('layout.done')}</p>
        </section>

        <section className={`panel card-stat${paceClass(course)}`} data-card="pace">
          <h2 className="small">{paceText(course)}</h2>
          <p className="hint">{t('layout.pace.base', { expected: course.expected })}</p>
        </section>

        <section className="panel card-stat" data-card="ends">
          <h2 className="small">
            {course.last_lesson_date ? longDate(course.last_lesson_date) : '—'}
          </h2>
          <p className="hint">
            {course.last_lesson_date
              ? t('layout.planEnds')
              : t('layout.planDoesNotFit', { count: course.missing })}
          </p>
        </section>

        {course.term && (
          <section
            className={`panel card-stat ${course.term.balance < 0 ? 'bad' : 'good'}`}
            data-card="term"
          >
            <h2>{balanceText(course.term.balance)}</h2>
            <p className="hint">
              {t(course.term.balance < 0 ? 'layout.termShort' : 'layout.termSpare', {
                term: course.term.name,
              })}
            </p>
          </section>
        )}
      </div>

      {course.next.length > 0 && (
        <section className="panel">
          <h3>{t('layout.next')}</h3>
          <ul className="progress-next">
            {course.next.map((lesson) => (
              <li key={lesson.number}>
                <span className="when">
                  {shortDate(lesson.date)} <em>{shortWeekday(lesson.date)}</em>
                </span>
                <span className="plan-number">{lesson.number}</span>
                <span className="what">{lesson.title}</span>
                {lesson.section_title && (
                  <span className="hint">{lesson.section_title}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <h3>{t('layout.byTerm')}</h3>
        <table className="terms-table">
          <thead>
            <tr>
              <th>{t('layout.term')}</th>
              <th>{t('layout.slots')}</th>
              <th>{t('layout.lessons')}</th>
              <th>{t('layout.balance')}</th>
            </tr>
          </thead>
          <tbody>
            {course.terms.map((term) => (
              <tr key={term.id ?? 'outside'}>
                <td>
                  {term.name}
                  {term.start && (
                    <span className="hint">
                      {shortDate(term.start)} — {shortDate(term.end)}
                    </span>
                  )}
                </td>
                <td>{term.slots}</td>
                <td>{term.lessons}</td>
                <td className={term.balance < 0 ? 'bad' : 'good'}>
                  {balanceText(term.balance)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h3>{t('layout.counters')}</h3>
        <ul className="progress-counters">
          <li>
            <b>{course.slots_total}</b> {t('layout.slotsTotal')}
          </li>
          <li>
            <b>{course.free_slots}</b> {t('layout.freeSlots')}
          </li>
          <li>
            <b>{course.extra}</b> {t('layout.extra')}
          </li>
          <li>
            <b>{course.cancelled}</b> {t('layout.cancelled')}
            {course.cancelled > 0 && (
              <span className="hint">
                {Object.entries(course.cancelled_by_reason)
                  .map(
                    ([reason, count]) => `${reason || t('layout.noReason')}: ${count}`,
                  )
                  .join(' · ')}
              </span>
            )}
          </li>
        </ul>
      </section>

      <div className="actions wrap">
        <button type="button" onClick={() => navigate('/plan')}>
          {t('layout.toPlan')}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => navigate('/schedule')}
        >
          {t('layout.toSchedule')}
        </button>
      </div>
    </div>
  )

  if (courses === null) {
    return (
      <main className="page wide">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('layout.title')}</h1>
      </header>

      <p className="hint">{t('layout.hint')}</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!courses.length ? (
        <EmptyState
          title={t('layout.needClass.title')}
          actions={
            <button type="button" onClick={() => navigate('/classes')}>
              {t('layout.needClass.action')}
            </button>
          }
        >
          {t('layout.needClass.hint')}
        </EmptyState>
      ) : (
        <ul className="progress-list">
          {courses.map((course) => (
            <li className="panel" key={course.id} data-course={course.id}>
              <button
                type="button"
                className="progress-head"
                aria-expanded={opened === course.id}
                onClick={() => setOpened(opened === course.id ? null : course.id)}
              >
                <span className="course">
                  {opened === course.id ? '▾' : '▸'} {course.name}
                </span>
                <span className="where">{whereText(course)}</span>
                <span className={`pace${paceClass(course)}`}>{paceText(course)}</span>
                <span className="term">
                  {course.term
                    ? `${course.term.name}: ${balanceText(course.term.balance)}`
                    : '—'}
                </span>
              </button>

              {opened === course.id && details(course)}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
