import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Markdown from './Markdown'
import {
  createPlanNode,
  fetchSlotCard,
  updatePlanNode,
  updateSlot,
} from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'

const LessonPanel = lazy(() => import('./LessonPanel'))

const FIELDS = ['objectives', 'body', 'formative', 'homework']

/**
 * Работа с одним уроком: что на нём, что задавали, что записали.
 *
 * Своей страницы у урока долго не было, и это оказалось главной пропажей.
 * «Сегодня» отвечал на вопрос «как устроен день», план — «из чего состоит
 * курс», а место, куда учитель приходит **работать с конкретным занятием**,
 * было размазано между ними: содержание правилось окном из таблицы плана,
 * тема подтверждалась на дне, работа задавалась оттуда же, и ни один из
 * этих экранов не был про урок.
 *
 * Здесь он целиком и в одном месте. Заходят сюда одинаково для прошлого,
 * сегодняшнего и будущего — разница только в том, какие действия имеют
 * смысл: подтвердить можно то, что уже случилось, а подготовиться можно к
 * чему угодно.
 *
 * Листается страница **по своему курсу**, а не по дню: «что было на
 * прошлом» — вопрос про этот же класс, а не про то, что стояло следующим
 * часом у другого.
 *
 * Своего расчёта здесь нет ни одного: содержание из плана, тема из
 * раскладки, работы из своих же связей — всё приходит одним ответом
 * (`GET /api/slots/<id>/card/`).
 */
export default function LessonScreen({ onLoggedOut }) {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()

  const [card, setCard] = useState(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false) // панель содержания
  const [form, setForm] = useState(null) // 'rename' | 'insert' | 'cancel'
  const [text, setText] = useState('')
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () => fetchSlotCard(id).then(setCard).catch(handleError),
    [id, handleError],
  )

  useEffect(() => {
    setCard(null)
    setForm(null)
    load()
  }, [load])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await load()
      setForm(null)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  if (!card) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const topic = card.topic
  const may = card.may_write
  // подтверждать можно только то, что уже случилось: нажатая накануне
  // кнопка стала бы ложью после утренней пожарной тревоги
  const done = card.date <= today()

  const open = (kind) => {
    setForm(kind)
    setText(kind === 'rename' ? topic.title : '')
  }

  const submit = (event) => {
    event.preventDefault()
    const value = text.trim()

    if (form === 'cancel') {
      run(() => updateSlot(card.id, { is_cancelled: true, reason: value }))
      return
    }
    if (!value) return

    if (form === 'rename') run(() => updatePlanNode(topic.id, { title: value }))
    else
      run(() =>
        createPlanNode({
          course: card.course.id,
          parent: topic.section_id,
          title: value,
          // перед предложенным уроком: «мы всё ещё на синусе» значит, что
          // сегодняшнее занятие идёт до него
          before: topic.id,
        }),
      )
  }

  return (
    <main className="page">
      <div className="agenda-bar">
        <button
          type="button"
          className="secondary"
          disabled={!card.previous}
          onClick={() => navigate(`/lesson/${card.previous}`)}
        >
          ←
        </button>
        <button
          type="button"
          className="secondary"
          disabled={!card.next}
          onClick={() => navigate(`/lesson/${card.next}`)}
        >
          →
        </button>
        <Link to="/today" className="link">
          {t('lessonScreen.toDay')}
        </Link>
      </div>

      {/* шапка колонкой: сначала «когда и у кого», потом сама тема. В ряд
          они вставали по краям страницы, и заголовок оказывался справа */}
      <header className="lesson-title-head">
        <p className="hint">
          {longDate(card.date)} ·{' '}
          {t('today.lessonNumber', { number: card.lesson_number })} ·{' '}
          {card.course.name}
        </p>
        <h1>{topic ? topic.title : t('agenda.noTopic')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {card.is_cancelled && (
        <p className="hint warning">
          {t('today.cancelled')}
          {card.reason && `: ${card.reason}`}{' '}
          {may && (
            <button
              type="button"
              className="link"
              disabled={busy}
              onClick={() =>
                run(() => updateSlot(card.id, { is_cancelled: false, reason: '' }))
              }
            >
              {t('agenda.menu.restore')}
            </button>
          )}
        </p>
      )}

      <section className="panel">
        {!topic ? (
          <p className="hint">{t('today.noTopic')}</p>
        ) : (
          <>
            <p className="hint">
              {card.confirmed ? (
                <span className="badge state good">{t('lessonScreen.recorded')}</span>
              ) : (
                t('today.suggested')
              )}
            </p>

            {form === 'rename' || form === 'insert' ? (
              <form className="row" onSubmit={submit}>
                <input
                  autoFocus
                  value={text}
                  maxLength={200}
                  aria-label={t(
                    form === 'rename' ? 'today.renameTitle' : 'today.insertTitle',
                  )}
                  placeholder={t(
                    form === 'rename' ? 'today.renameTitle' : 'today.insertTitle',
                  )}
                  onChange={(event) => setText(event.target.value)}
                />
                <button type="submit" disabled={busy}>
                  {t('common.save')}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setForm(null)}
                >
                  {t('common.cancel')}
                </button>
              </form>
            ) : (
              may && (
                <div className="row">
                  {done && !card.confirmed && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => run(() => updateSlot(card.id, { lesson: topic.id }))}
                    >
                      {t('today.confirm')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="secondary compact"
                    disabled={busy}
                    onClick={() => setEditing(true)}
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
                </div>
              )
            )}
          </>
        )}
      </section>

      {topic && FIELDS.some((field) => topic[field]) && (
        <section className="panel">
          {FIELDS.filter((field) => topic[field]).map((field) => (
            <div className="lesson-field" key={field}>
              <span className="hint">{t(`lesson.fields.${field}`)}</span>
              <Markdown text={topic[field]} />
            </div>
          ))}
        </section>
      )}

      <section className="panel">
        <h2 className="panel-title">{t('lessonScreen.works')}</h2>

        {card.works.length === 0 ? (
          <p className="hint">{t('lessonScreen.noWorks')}</p>
        ) : (
          <ul className="work-links">
            {card.works.map((work) => (
              <li key={work.id}>
                <Link to={`/works/${work.id}`}>{work.title}</Link>
                <span className={`badge state-${work.state}`}>
                  {t(`works.state.${work.state}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {may && !card.is_cancelled && (
        <div className="row">
          {form === 'cancel' ? (
            <form className="row" onSubmit={submit}>
              <input
                autoFocus
                value={text}
                maxLength={200}
                placeholder={t('agenda.menu.cancelReason')}
                aria-label={t('agenda.menu.cancelReason')}
                onChange={(event) => setText(event.target.value)}
              />
              <button type="submit" disabled={busy}>
                {t('agenda.menu.cancelSubmit')}
              </button>
              <button type="button" className="secondary" onClick={() => setForm(null)}>
                {t('agenda.menu.cancelAbort')}
              </button>
            </form>
          ) : (
            <button
              type="button"
              className="secondary compact"
              disabled={busy}
              onClick={() => open('cancel')}
            >
              {t('agenda.menu.cancel')}
            </button>
          )}
        </div>
      )}

      {editing && topic && (
        <Suspense fallback={null}>
          <LessonPanel
            nodeId={topic.id}
            onClose={() => setEditing(false)}
            onSaved={() => load()}
          />
        </Suspense>
      )}
    </main>
  )
}
