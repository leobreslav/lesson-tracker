import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import EmptyState from './EmptyState'
import { fetchProgress } from './api'
import { longDate, shortDate, shortWeekday } from './dates'

/**
 * «Состояние курсов» — экран состояния, а не список уроков.
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
        // разворачиваем тот, где проблема: экран затем и нужен, чтобы её
        // увидеть. Проблем нет — все свёрнуты, смотреть не на что
        const trouble = result.courses.find((course) => course.reserve < 0)
        if (trouble) setOpened(trouble.id)
        else if (result.courses.length === 1) setOpened(result.courses[0].id)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })

    return () => {
      cancelled = true
    }
  }, [handleError])

  /** Всё сводится к одному: план помещается в год или нет. */
  const short = (course) => course.reserve < 0

  const statusText = (course) =>
    short(course)
      ? t('status.status.short', { count: -course.reserve })
      : t('status.status.fine')

  /** «урок 14 из 44 · Тригонометрия». */
  const whereText = (course) => {
    if (!course.lessons_total) return t('status.where.noPlan')
    if (!course.current) return t('status.where.finished', { count: course.done })

    return [
      t('status.where.at', {
        number: course.current.number,
        total: course.lessons_total,
      }),
      course.current.section_title,
    ]
      .filter(Boolean)
      .join(' · ')
  }

  const signed = (value) => `${value > 0 ? '+' : ''}${value}`

  const details = (course) => (
    <div className="progress-details">
      <div className="cards">
        <section
          className={`panel card-stat ${short(course) ? 'bad' : 'good'}`}
          data-card="reserve"
        >
          <h2>{signed(course.reserve)}</h2>
          <p className="hint">
            {t(short(course) ? 'status.reserveShort' : 'status.reserveSpare')}
          </p>
        </section>

        <section className="panel card-stat" data-card="losses">
          <h2>{course.cancelled}</h2>
          <p className="hint">{t('status.cancelled')}</p>
          {course.cancelled > 0 && (
            <p className="hint">
              {Object.entries(course.cancelled_by_reason)
                .map(([reason, count]) => `${reason || t('status.noReason')}: ${count}`)
                .join(' · ')}
            </p>
          )}
        </section>

        <section className="panel card-stat" data-card="growth">
          {course.baseline ? (
            <>
              <h2>{signed(course.baseline.added)}</h2>
              <p className="hint">
                {t('status.grown', {
                  date: shortDate(course.baseline.created_at.slice(0, 10)),
                })}
              </p>
              {course.baseline.removed > 0 && (
                <p className="hint">
                  {t('status.dropped', { count: course.baseline.removed })}
                </p>
              )}
            </>
          ) : (
            <>
              <h2 className="small">—</h2>
              <p className="hint">{t('status.noBaseline')}</p>
            </>
          )}
        </section>

        <section className="panel card-stat" data-card="ends">
          <h2 className="small">
            {course.last_lesson_date ? shortDate(course.last_lesson_date) : '—'}
          </h2>
          <p className="hint">
            {course.last_lesson_date
              ? t('status.endsOn', { year: shortDate(course.year_end) })
              : t('status.doesNotFit', { count: course.missing })}
          </p>
        </section>
      </div>

      {/* про год говорим отдельно: на плашку состояния это не влияет */}
      {course.last_lesson_date && course.last_lesson_date > course.year_end && (
        <p className="hint warning">
          {t('status.pastYear', { year: shortDate(course.year_end) })}
        </p>
      )}

      {course.baseline?.themes.length > 0 && (
        <section className="panel">
          <h3>{t('status.grownThemes')}</h3>
          <ul className="progress-themes">
            {course.baseline.themes.map((theme) => (
              <li key={theme.title ?? 'loose'}>
                <span>{theme.title ?? t('status.looseTheme')}</span>
                <b>{signed(theme.added)}</b>
              </li>
            ))}
          </ul>
        </section>
      )}

      {course.next.length > 0 && (
        <section className="panel">
          <h3>{t('status.next')}</h3>
          <ul className="progress-next">
            {course.next.map((lesson) => (
              <li key={lesson.number}>
                <span className="when">
                  {shortDate(lesson.date)} <em>{shortWeekday(lesson.date)}</em>
                </span>
                <span className="what">{lesson.title}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="actions wrap">
        <button type="button" onClick={() => navigate('/plan')}>
          {t('status.toPlan')}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => navigate('/schedule')}
        >
          {t('status.toSchedule')}
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
        <h1>{t('status.title')}</h1>
      </header>

      <p className="hint">{t('status.hint')}</p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {!courses.length ? (
        <EmptyState
          title={t('status.needClass.title')}
          actions={
            <button type="button" onClick={() => navigate('/classes')}>
              {t('status.needClass.action')}
            </button>
          }
        >
          {t('status.needClass.hint')}
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
                <span className="reserve">
                  {t('status.reserve', { count: course.reserve })}
                </span>
                <span className={`badge state ${short(course) ? 'bad' : 'good'}`}>
                  {statusText(course)}
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
