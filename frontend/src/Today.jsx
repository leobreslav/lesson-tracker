import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import DebtsDialog from './DebtsDialog'
import EmptyState from './EmptyState'
import Markdown from './Markdown'
import WorkDialog from './WorkDialog'
import {
  createPlanNode,
  createWork,
  fetchCourses,
  fetchSlotDay,
  fetchUnclosed,
  updatePlanNode,
  updateSlot,
} from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'
import { remember, remembered } from './remember'

const LessonPanel = lazy(() => import('./LessonPanel'))

/**
 * День учителя одним экраном.
 *
 * Так он и выглядит: пришёл утром, посмотрел, что сегодня, провёл занятие
 * глядя в план, объявил практику, задал домашнее. Раньше это было четыре
 * экрана, и между ними приходилось помнить, где ты.
 *
 * **День вперёд, а не курс.** Экран был устроен наоборот — сначала выбрать
 * класс, потом день, — и на нём было неудобно ровно то, ради чего его
 * открывают: утренний вопрос «что у меня сегодня» это четыре занятия трёх
 * разных курсов, и вечерний «что закрыть» тоже. Курс остался фильтром: он
 * нужен, когда думают об одном классе.
 *
 * Своего расчёта здесь нет ни одного — содержание из плана, тема из
 * раскладки, работы из своих же связей, — и это намеренно: экран собирается
 * из готового, а второй расчёт над теми же данными однажды разойдётся с
 * первым.
 *
 * Тему занятие **подсказывает**, а записывает её человек одним нажатием, и
 * только у прошедшего дня: нажатая накануне кнопка стала бы ложью после
 * утренней пожарной тревоги. Готовиться накануне это не мешает — план
 * правится вперёд и о датах ничего не знает.
 */
export default function Today({ onLoggedOut }) {
  const { t } = useTranslation()
  const [courses, setCourses] = useState(null)
  const [only, setOnly] = useState(() => remembered('today.course', null))
  const [date, setDate] = useState(today())
  const [day, setDay] = useState(null)
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(null) // {slot, homework}
  const [opened, setOpened] = useState(null) // строка плана в панели
  const [debts, setDebts] = useState([])
  const [closing, setClosing] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  useEffect(() => {
    fetchCourses().then(setCourses).catch(handleError)
  }, [handleError])

  const load = useCallback(
    () =>
      Promise.all([fetchSlotDay(date), fetchUnclosed()])
        .then(([answer, owed]) => {
          setDay(answer)
          setDebts(owed.slots)
        })
        .catch(handleError),
    [date, handleError],
  )

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

  const filter = (id) => {
    setOnly(id)
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

  const shown = (day?.lessons ?? []).filter(
    (slot) => only === null || slot.course.id === only,
  )
  // подтверждать можно только то, что уже случилось
  const done = day ? day.date <= today() : false

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('today.title')}</h1>
      </header>

      {/* чипы — фильтр, а не выбор экрана: по умолчанию виден весь день */}
      <div className="agenda-bar">
        <span className="year-picker">
          <button
            type="button"
            className={only === null ? 'chip active' : 'chip'}
            onClick={() => filter(null)}
          >
            {t('today.allCourses')}
          </button>
          {courses.map((course) => (
            <button
              type="button"
              key={course.id}
              className={course.id === only ? 'chip active' : 'chip'}
              onClick={() => filter(course.id)}
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

      {/* Настойчивость стоит **на дороге**, по которой человек и так идёт:
          напоминание сбоку игнорируется на третий день, а «Сегодня» он
          открывает, чтобы вести урок. Одно движение до того, как начнёт. */}
      {debts.length > 0 && (
        <p className="hint warning" data-debts={debts.length}>
          {t('status.unclosed', { count: debts.length })}{' '}
          <button type="button" className="link" onClick={() => setClosing(true)}>
            {t('status.closeDebts')}
          </button>
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

          {shown.length === 0 ? (
            <p className="hint">{t('today.noLesson')}</p>
          ) : (
            shown.map((slot) => (
              <SlotCard
                key={slot.id}
                slot={slot}
                busy={busy}
                done={done}
                onConfirm={() =>
                  run(() => updateSlot(slot.id, { lesson: slot.topic.id }))
                }
                onHomework={() => setAdding({ slot, homework: slot.topic?.homework })}
                onOpen={() => setOpened(slot.topic.id)}
                onRename={(title) => run(() => updatePlanNode(slot.topic.id, { title }))}
                onInsert={(title) =>
                  run(() =>
                    createPlanNode({
                      course: slot.course.id,
                      parent: slot.topic.section_id,
                      title,
                      // перед предложенным уроком: «мы всё ещё на синусе»
                      // значит, что сегодняшнее занятие идёт до него
                      before: slot.topic.id,
                    }),
                  )
                }
              />
            ))
          )}
        </>
      )}

      {adding && (
        <WorkDialog
          courseId={adding.slot.course.id}
          preset={{
            title: t('today.homeworkTitle'),
            description: adding.homework ?? '',
            slot: adding.slot.id,
          }}
          busy={busy}
          onSubmit={(fields) => run(() => createWork(fields))}
          onClose={() => setAdding(null)}
        />
      )}

      {closing && (
        <DebtsDialog
          busy={busy}
          onDone={() => {
            setClosing(false)
            load()
          }}
          onClose={() => setClosing(false)}
        />
      )}

      {opened && (
        <Suspense fallback={null}>
          <LessonPanel
            nodeId={opened}
            onClose={() => setOpened(null)}
            onSaved={() => load()}
          />
        </Suspense>
      )}
    </main>
  )
}

/**
 * Одно занятие дня: чем занимаемся, что задавали, что дальше.
 *
 * Четыре поля плана показываются как есть и только непустые: пустые
 * заголовки на экране, куда смотрят посреди урока, — чистый шум.
 *
 * Правки плана живут здесь же, и это не удобство, а место. Расхождение
 * замечают **накануне**, когда готовятся: «до конца четверти шесть занятий,
 * а в теме осталось восемь». Уходить за этим в «Учебный план», искать
 * строку среди сорока и возвращаться — ровно та заминка, из-за которой
 * готовиться будут не здесь.
 */
function SlotCard({
  slot,
  busy,
  done,
  onConfirm,
  onHomework,
  onOpen,
  onRename,
  onInsert,
}) {
  const { t } = useTranslation()
  const [form, setForm] = useState(null) // 'rename' | 'insert'
  const [title, setTitle] = useState('')
  const topic = slot.topic

  const open = (kind) => {
    setForm(kind)
    setTitle(kind === 'rename' ? topic.title : '')
  }

  const submit = (event) => {
    event.preventDefault()
    const value = title.trim()
    if (!value) return

    ;(form === 'rename' ? onRename : onInsert)(value)
    setForm(null)
  }

  return (
    <section className="panel lesson-card">
      <div className="panel-head spread">
        <h2 className="section-title">
          {t('today.lessonNumber', { number: slot.lesson_number })} ·{' '}
          {slot.course.name}
          {topic && <> · {topic.title}</>}
        </h2>
        {slot.is_cancelled && (
          <span className="badge">
            {t('today.cancelled')}
            {slot.reason && `: ${slot.reason}`}
          </span>
        )}
      </div>

      {!topic ? (
        <p className="hint">{t('today.noTopic')}</p>
      ) : (
        <>
          {!slot.confirmed && (
            <p className="hint">
              {t('today.suggested')}
              {done && (
                <>
                  {' '}
                  <button
                    type="button"
                    className="link"
                    disabled={busy}
                    onClick={onConfirm}
                  >
                    {t('today.confirm')}
                  </button>
                </>
              )}
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
        {slot.works.map((work) => (
          <li key={work.id}>
            <Link to={`/works/${work.id}`}>{work.title}</Link>
            <span className={`badge state-${work.state}`}>
              {t(`works.state.${work.state}`)}
            </span>
          </li>
        ))}
      </ul>

      {form ? (
        <form className="row" onSubmit={submit}>
          <input
            autoFocus
            value={title}
            maxLength={200}
            aria-label={t(form === 'rename' ? 'today.renameTitle' : 'today.insertTitle')}
            placeholder={t(
              form === 'rename' ? 'today.renameTitle' : 'today.insertTitle',
            )}
            onChange={(event) => setTitle(event.target.value)}
          />
          <button type="submit" disabled={busy}>
            {t('common.save')}
          </button>
          <button type="button" className="secondary" onClick={() => setForm(null)}>
            {t('common.cancel')}
          </button>
        </form>
      ) : (
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
          {topic && (
            <>
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={onOpen}
              >
                {t('today.editContent')}
              </button>
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => open('rename')}
              >
                {t('today.rename')}
              </button>
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => open('insert')}
              >
                {t('today.insert')}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}
