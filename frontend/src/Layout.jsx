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

  /**
   * Прогресс по плану: три связанных числа одной плашкой.
   *
   * Проведено, осталось и всего — это одно утверждение, разложенное на
   * три части, и врозь они читаются как три разных показателя.
   *
   * Дефицит на числа не влияет: «осталось 30» значит тридцать уроков
   * плана, а хватит ли им дней — отдельный вопрос, и у него своё
   * предупреждение в шапке.
   */
  const progressCard = (course) => {
    if (!course.lessons_total) {
      return (
        <section className="panel card-stat" data-card="progress">
          <p className="hint">{t('status.where.noPlan')}</p>
          <button type="button" className="link" onClick={() => navigate('/plan')}>
            {t('status.fillPlan')}
          </button>
        </section>
      )
    }

    const left = course.lessons_total - course.done

    return (
      <section className="panel card-stat" data-card="progress">
        <h2>{t('status.doneOf', { done: course.done, total: course.lessons_total })}</h2>
        <p className="hint">{t('status.left', { count: left })}</p>
      </section>
    )
  }

  const details = (course) => (
    <div className="progress-details">
      <div className="cards">
        {progressCard(course)}

        <section
          className={`panel card-stat ${short(course) ? 'bad' : 'good'}`}
          data-card="reserve"
        >
          <h2>{signed(course.reserve)}</h2>
          <p className="hint">
            {t(short(course) ? 'status.reserveShort' : 'status.reserveSpare')}
          </p>
        </section>

        {/* насколько расписание разошлось с исходным: добавили минус
            отменили. С резервом не путать — тот про план, этот про дни */}
        <section className="panel card-stat" data-card="changes">
          <h2>{signed(course.extra - course.cancelled)}</h2>
          <p className="hint">{t('status.changes')}</p>
          <p className="hint">
            {t('status.changesDetail', {
              cancelled: course.cancelled,
              extra: course.extra,
            })}
          </p>
        </section>

        {/* два числа, а не сальдо: рост съедает резерв, удаление означает
            выкинутый материал, и «плюс три минус три» тут не ноль */}
        <section className="panel card-stat" data-card="growth">
          {course.baseline ? (
            <>
              <p className="pair">
                <b>{signed(course.baseline.added)}</b> {t('status.addedToPlan')}
              </p>
              <p className="pair">
                <b>{course.baseline.removed}</b> {t('status.droppedFromPlan')}
              </p>
              <p className="hint">
                {t('status.grown', {
                  date: shortDate(course.baseline.approved_at.slice(0, 10)),
                })}
              </p>
            </>
          ) : (
            <>
              <p className="hint">{t('status.noBaseline')}</p>
              <button type="button" className="link" onClick={() => navigate('/plan')}>
                {t('status.sendForApproval')}
              </button>
            </>
          )}
        </section>
      </div>

      {/* про год говорим отдельно: на плашку состояния это не влияет */}
      {course.last_lesson_date && course.last_lesson_date > course.year_end && (
        <p className="hint warning">
          {t('status.pastYear', {
            date: shortDate(course.last_lesson_date),
            year: shortDate(course.year_end),
          })}
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
                {/* число со знаком, а не «резерв −28 уроков»: смысл минуса
                    проговаривает плашка справа, и повторять его словами
                    значит спорить с ней на полстроки */}
                {/* дефицит говорит словами и рядом с плашкой состояния, а
                    не мелким текстом внизу: это главное, что нужно узнать */}
                {course.missing > 0 ? (
                  <span className="reserve overflow">
                    {t('status.overflow', { count: course.missing })}
                  </span>
                ) : (
                  <span className="reserve">
                    {t('status.reserveLabel')}: {signed(course.reserve)}
                  </span>
                )}
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
