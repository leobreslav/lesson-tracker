import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import EmptyState from './EmptyState'
import Markdown from './Markdown'
import WorkDialog from './WorkDialog'
import { createWork, fetchCourses, fetchLessonDay, updateSlot } from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'
import { remember, remembered } from './remember'

/**
 * День учителя одним экраном.
 *
 * Так он и выглядит: выбрал класс, попал в текущий урок, ведёт его глядя в
 * план, объявляет практику, задаёт домашнее. Раньше это было четыре экрана,
 * и между ними приходилось помнить, где ты.
 *
 * Своего расчёта здесь нет ни одного — содержание из плана, тема из
 * раскладки, работы из своих связей, — и это намеренно: экран собирается из
 * готового, а второй расчёт над теми же данными однажды разойдётся с первым.
 *
 * Тему урока страница **подсказывает**, а записывает её человек одним
 * нажатием. Разница не косметическая: подсказка позиционная и съезжает от
 * любой правки плана, а запись держится за дату.
 */
export default function Today({ onLoggedOut }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState(null)
  const [courseId, setCourseId] = useState(() => remembered('today.course', null))
  const [date, setDate] = useState(today())
  const [day, setDay] = useState(null)
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(null) // {lesson, homework}
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    fetchCourses()
      .then((mine) => {
        setCourses(mine)
        setCourseId((current) =>
          mine.some((course) => course.id === current) ? current : mine[0]?.id ?? null,
        )
      })
      .catch(handleError)
  }, [handleError])

  const load = useCallback(() => {
    if (!courseId) return Promise.resolve()

    return fetchLessonDay(courseId, date).then(setDay).catch(handleError)
  }, [courseId, date, handleError])

  useEffect(() => {
    load()
  }, [load])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await load()
      setAdding(null)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const choose = (id) => {
    setCourseId(id)
    remember('today.course', id)
  }

  if (courses === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  if (!courses.length) {
    return (
      <main className="page narrow">
        <header className="page-header">
          <h1>{t('today.title')}</h1>
        </header>
        <EmptyState title={t('today.noCourses')}>{t('today.noCoursesHint')}</EmptyState>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('today.title')}</h1>
      </header>

      <div className="agenda-bar">
        <span className="year-picker">
          {courses.map((course) => (
            <button
              type="button"
              key={course.id}
              className={course.id === courseId ? 'chip active' : 'chip'}
              onClick={() => choose(course.id)}
            >
              {course.name}
            </button>
          ))}
        </span>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {day && (
        <>
          <div className="agenda-bar">
            <button
              type="button"
              className="secondary"
              disabled={!day.previous}
              onClick={() => setDate(day.previous)}
            >
              ←
            </button>
            <button type="button" className="secondary" onClick={() => setDate(today())}>
              {t('agenda.today')}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!day.next}
              onClick={() => setDate(day.next)}
            >
              →
            </button>
            <strong>{longDate(day.date)}</strong>
          </div>

          {day.lessons.length === 0 ? (
            <p className="hint">{t('today.noLesson')}</p>
          ) : (
            day.lessons.map((lesson) => (
              <LessonCard
                key={lesson.id}
                lesson={lesson}
                busy={busy}
                onConfirm={() =>
                  run(() => updateSlot(lesson.id, { covered: lesson.topic.id }))
                }
                onHomework={() => setAdding({ lesson, homework: lesson.topic?.homework })}
              />
            ))
          )}
        </>
      )}

      {adding && (
        <WorkDialog
          courseId={courseId}
          preset={{
            title: t('today.homeworkTitle'),
            description: adding.homework ?? '',
            lesson: adding.lesson.id,
          }}
          busy={busy}
          onSubmit={(fields) => run(() => createWork(fields))}
          onClose={() => setAdding(null)}
        />
      )}
    </main>
  )
}

/**
 * Один урок дня: чем занимаемся, что задавали, что дальше.
 *
 * Четыре поля плана показываются как есть и только непустые: пустые
 * заголовки на экране, куда смотрят посреди урока, — чистый шум.
 */
function LessonCard({ lesson, busy, onConfirm, onHomework }) {
  const { t } = useTranslation()
  const topic = lesson.topic

  return (
    <section className="panel lesson-card">
      <div className="panel-head spread">
        <h2 className="section-title">
          {t('today.lessonNumber', { number: lesson.lesson_number })}
          {topic && <> · {topic.title}</>}
        </h2>
        {lesson.is_cancelled && (
          <span className="badge">
            {t('today.cancelled')}
            {lesson.reason && `: ${lesson.reason}`}
          </span>
        )}
      </div>

      {!topic ? (
        <p className="hint">{t('today.noTopic')}</p>
      ) : (
        <>
          {!lesson.confirmed && (
            <p className="hint">
              {t('today.suggested')}{' '}
              <button type="button" className="link" disabled={busy} onClick={onConfirm}>
                {t('today.confirm')}
              </button>
            </p>
          )}

          {['objectives', 'body', 'formative', 'homework']
            .filter((field) => topic[field])
            .map((field) => (
              <div className="lesson-field" key={field}>
                <span className="hint">{t(`lesson.fields.${field}`)}</span>
                <Markdown text={topic[field]} />
              </div>
            ))}
        </>
      )}

      <ul className="work-links">
        {lesson.works.map((work) => (
          <li key={work.id}>
            <Link to={`/works/${work.id}`}>{work.title}</Link>
            <span className={`badge state-${work.state}`}>
              {t(`works.state.${work.state}`)}
            </span>
          </li>
        ))}
      </ul>

      <div className="row">
        {/* «задать как домашнее» подставляет рекомендованный текст плана:
            фактическая домашка — событие урока, и от рекомендованной она
            законно отличается */}
        <button
          type="button"
          className="secondary compact"
          disabled={busy}
          onClick={onHomework}
        >
          {t('today.setHomework')}
        </button>
      </div>
    </section>
  )
}
