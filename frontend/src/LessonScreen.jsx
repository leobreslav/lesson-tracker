import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import LessonAttendance from './LessonAttendance'
import Markdown from './Markdown'
import { iconFor } from './fileKind'
import {
  addLinkAttachment,
  createPlanNode,
  deleteAttachment,
  fetchSlotCard,
  openAttachment,
  updatePlanNode,
  updateSlot,
  uploadAttachment,
} from './api'
import { today } from './calendarLogic'
import { longDate, shortDate } from './dates'

const LessonPanel = lazy(() => import('./LessonPanel'))

// содержание урока без домашнего задания: его объявляют в конце, и на
// странице оно стоит отдельным, последним блоком
const CONTENT = ['objectives', 'body', 'formative']

/**
 * Работа с одним уроком: что на нём, кто был, что задавали.
 *
 * Своей страницы у урока долго не было, и это оказалось главной пропажей.
 * «Сегодня» отвечал на вопрос «как устроен день», план — «из чего состоит
 * курс», а место, куда учитель приходит **работать с конкретным занятием**,
 * было размазано между ними.
 *
 * **Порядок блоков — порядок урока**, а не порядок наших таблиц: отметить
 * пришедших, вести по содержанию, объявить работы, показать материалы,
 * задать домашнее. Экран, собранный по сущностям, заставлял бы каждый раз
 * искать глазами то, что делают следующим.
 *
 * Над блоками стоит тема, потому что от неё зависит всё остальное. Пока она
 * не записана, страница предлагает **выбрать** её, а не только подтвердить
 * подсказку: раскладка подсказывает позиционно и в обычный день права, но
 * необычным день бывает чаще, чем кажется — перенесли контрольную,
 * вернулись к теме, поменяли порядок.
 *
 * Заходят сюда одинаково для прошлого, сегодняшнего и будущего — разница в
 * том, какие действия имеют смысл: записать можно то, что уже случилось, а
 * подготовиться можно к чему угодно.
 *
 * Своего расчёта здесь нет ни одного: всё приходит одним ответом
 * (`GET /api/slots/<id>/card/`), кроме журнала — он спрашивает себя сам,
 * потому что меняется чаще всего остального.
 */
export default function LessonScreen({ onLoggedOut }) {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()

  const [card, setCard] = useState(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false) // панель содержания
  const [form, setForm] = useState(null) // 'rename' | 'insert' | 'cancel' | 'link'
  const [text, setText] = useState('')
  const [link, setLink] = useState({ url: '', title: '' })
  const [choice, setChoice] = useState('') // выбранная строка плана
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState(null)

  const fileInput = useRef(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () =>
      fetchSlotCard(id)
        .then((answer) => {
          setCard(answer)
          setChoice(answer.topic ? String(answer.topic.id) : '')
        })
        .catch(handleError),
    [id, handleError],
  )

  useEffect(() => {
    setCard(null)
    setForm(null)
    setPicking(false)
    load()
  }, [load])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await load()
      setForm(null)
      setPicking(false)
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
  // записать можно только то, что уже случилось: нажатая накануне кнопка
  // стала бы ложью после утренней пожарной тревоги
  const done = card.date <= today()
  const choosing = may && (picking || (done && !card.confirmed && card.options.length))

  const open = (kind) => {
    setForm(kind)
    setText(kind === 'rename' ? topic.title : '')
    setLink({ url: '', title: '' })
  }

  const submit = (event) => {
    event.preventDefault()

    if (form === 'link') {
      if (!link.url.trim()) return
      run(() =>
        addLinkAttachment({
          planRow: topic.id,
          url: link.url.trim(),
          title: link.title.trim() || link.url.trim(),
        }),
      )
      return
    }

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

      {/* шапка колонкой: сначала «когда и у кого», потом сама тема */}
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
        {choosing ? (
          <>
            <h2 className="panel-title">{t('lessonScreen.pickTopic')}</h2>
            <p className="hint">{t('lessonScreen.pickTopicHint')}</p>
            <div className="row">
              <select
                value={choice}
                aria-label={t('lessonScreen.pickTopic')}
                onChange={(event) => setChoice(event.target.value)}
              >
                {card.options.map((option) => (
                  <option key={option.id} value={option.id} disabled={!!option.taken}>
                    {option.number}. {option.title}
                    {option.taken &&
                      ` — ${t('lessonScreen.takenOn', {
                        date: shortDate(option.taken),
                      })}`}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busy || !choice}
                onClick={() =>
                  run(() => updateSlot(card.id, { lesson: Number(choice) }))
                }
              >
                {t('lessonScreen.bind')}
              </button>
              {picking && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPicking(false)}
                >
                  {t('common.cancel')}
                </button>
              )}
            </div>
          </>
        ) : !topic ? (
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
                  {/* выбрать тему можно там, где есть что записывать: у
                      будущего занятия это было бы прибиванием урока к дате,
                      а от него мы отказались — раскладка сама поглощает
                      срывы, а прибитый урок после отмены повисает */}
                  {done && (
                    <button
                      type="button"
                      className="secondary compact"
                      disabled={busy}
                      onClick={() => setPicking(true)}
                    >
                      {t('lessonScreen.changeTopic')}
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

      {/* 1. Кто пришёл — это делают до того, как начали */}
      <section className="panel">
        <h2 className="panel-title">{t('lessonScreen.attendance')}</h2>
        <LessonAttendance slotId={card.id} may={may} onError={handleError} />
      </section>

      {/* 2. Чем занимаемся */}
      <section className="panel">
        <h2 className="panel-title">{t('lessonScreen.content')}</h2>
        {!topic || !CONTENT.some((field) => topic[field]) ? (
          <p className="hint">{t('lessonScreen.noContent')}</p>
        ) : (
          CONTENT.filter((field) => topic[field]).map((field) => (
            <div className="lesson-field" key={field}>
              <span className="hint">{t(`lesson.fields.${field}`)}</span>
              <Markdown text={topic[field]} />
            </div>
          ))
        )}
      </section>

      {/* 3. Что решаем */}
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

      {/* 4. Чем пользуемся: файлы и ссылки строки плана */}
      <section className="panel">
        <h2 className="panel-title">{t('lessonScreen.materials')}</h2>

        {!topic?.attachments?.length ? (
          <p className="hint">{t('lessonScreen.noMaterials')}</p>
        ) : (
          <ul className="attachments">
            {topic.attachments.map((item) => (
              <li key={item.id} className="attachment">
                <span className="attachment-icon" aria-hidden="true">
                  {iconFor(item)}
                </span>
                {item.kind === 'link' ? (
                  <a href={item.url} target="_blank" rel="noreferrer" className="title">
                    {item.title}
                  </a>
                ) : (
                  <button
                    type="button"
                    className="link title"
                    onClick={() => openAttachment(item.id).catch(handleError)}
                  >
                    {item.title}
                  </button>
                )}
                {may && (
                  <button
                    type="button"
                    className="link remove"
                    title={t('common.delete')}
                    disabled={busy}
                    onClick={() => run(() => deleteAttachment(item.id))}
                  >
                    ✕
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {may &&
          topic &&
          (form === 'link' ? (
            <form className="row" onSubmit={submit}>
              <input
                autoFocus
                type="url"
                value={link.url}
                placeholder={t('lessonScreen.linkAddress')}
                aria-label={t('lessonScreen.linkAddress')}
                onChange={(event) => setLink({ ...link, url: event.target.value })}
              />
              <input
                value={link.title}
                maxLength={200}
                placeholder={t('lessonScreen.linkTitle')}
                aria-label={t('lessonScreen.linkTitle')}
                onChange={(event) => setLink({ ...link, title: event.target.value })}
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
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => open('link')}
              >
                {t('lessonScreen.addLink')}
              </button>
              {/* нативный input прячется: его подпись браузер рисует сам,
                  на своём языке и своей кнопкой — в ряду с остальными она
                  чужая и не переводится */}
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {t('lesson.addFile')}
              </button>
              <input
                ref={fileInput}
                type="file"
                className="hidden-file"
                aria-label={t('lesson.addFile')}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) run(() => uploadAttachment({ planRow: topic.id, file }))
                }}
              />
            </div>
          ))}
      </section>

      {/* 5. Что задаём на дом — последним, потому что объявляют его в конце */}
      <section className="panel">
        <h2 className="panel-title">{t('lessonScreen.homework')}</h2>
        {topic?.homework ? (
          <Markdown text={topic.homework} />
        ) : (
          <p className="hint">{t('lessonScreen.noHomework')}</p>
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
