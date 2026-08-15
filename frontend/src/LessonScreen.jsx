import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Collapsible from './Collapsible'
import LessonAttendance from './LessonAttendance'
import Markdown from './Markdown'
import WorkDialog from './WorkDialog'
import { useDismissable } from './UserMenu'
import { iconFor } from './fileKind'
import {
  addLinkAttachment,
  createWork,
  deleteAttachment,
  fetchSlotCard,
  openAttachment,
  updatePlanNode,
  updateSlot,
  uploadAttachment,
} from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'

// содержание урока без домашнего задания: его объявляют в конце, и на
// странице оно стоит отдельным, последним блоком
const CONTENT = ['objectives', 'body', 'formative']
const HOMEWORK = ['homework']

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
 * Над блоками стоит тема, потому что от неё зависит всё остальное. Здесь её
 * **подтверждают, а не выбирают**: что было на уроке, решает план, и не
 * угадал он — правят план, а подсказка меняется сама. Список плана из сорока
 * строк отвечал бы на тот же вопрос мимо плана, не оставляя следа, что он
 * разошёлся с реальностью.
 *
 * Снимается запись повторным нажатием на плашку «записано» — тем же приёмом,
 * что отметка в журнале и вердикт в проверке работ. Без него исправить
 * запись было бы нечем: «связать с другой строкой» здесь не предлагается.
 *
 * **Своего содержания у занятия нет ни одного поля.** Содержание, материалы
 * и домашнее задание — это строка учебного плана, показанная отсюда; правка
 * их меняет план, то есть программу курса. Так и должно быть: план остаётся
 * правдой о курсе именно потому, что его правят по факту.
 *
 * **Туннель открывается только подтверждённой связью.** Пока тема лишь
 * подсказана, править её отсюда нельзя вовсе — раскладка показала строку
 * позиционно, и она вполне может быть не той, а правка вслепую меняла бы
 * чужой урок молча. Идут за этим в «Учебный план», где строка видна в
 * окружении: над ней тема, под ней соседи, рядом даты и черта «сегодня».
 * Ссылка ведёт прямо на неё.
 *
 * Отсюда следствие, которое стоит знать заранее: **будущее занятие со своей
 * страницы не правится никогда**. Не «пока не подтвердил» — связать можно
 * только прошедшее, прибивание будущего урока к дате мы убрали сознательно.
 * Готовятся в плане, и это правило, а не временное состояние.
 *
 * Заходят сюда одинаково для прошлого, сегодняшнего и будущего — разница в
 * том, какие действия имеют смысл: записать можно то, что уже случилось, а
 * подготовиться можно к чему угодно.
 *
 * Кнопки в шапках карточек **все вторичные**, и это правило, а не вкус:
 * карточек пять, у каждой своё действие, и синяя в каждой шапке дала бы
 * пять спорящих главных кнопок на один экран. Синий остаётся за
 * подтверждением внутри формы — «Записать», «Сохранить».
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
  // {fields, draft} — какой блок правят и что в нём набрано. Правится
  // ровно один за раз: два черновика на экране означали бы два ответа на
  // вопрос «что сейчас сохранится»
  const [editing, setEditing] = useState(null)
  const [adding, setAdding] = useState(null) // 'work' | 'homework'
  const [form, setForm] = useState(null) // 'rename' | 'cancel' | 'link'
  const [text, setText] = useState('')
  const [link, setLink] = useState({ url: '', title: '' })
  const [menuOpen, setMenuOpen] = useState(false)
  const [error, setError] = useState(null)

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const menuRef = useDismissable(menuOpen, closeMenu)

  const fileInput = useRef(null)

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
  // записать можно только то, что уже случилось: нажатая накануне кнопка
  // стала бы ложью после утренней пожарной тревоги
  const done = card.date <= today()
  // одна и та же сущность в двух разделах: разница только в том, что
  // задали на дом, а что решают в классе
  const homework = card.works.filter((work) => work.is_homework)
  const classwork = card.works.filter((work) => !work.is_homework)
  // туннель в план открыт только записанной связью: подсказанную строку
  // правят там, где её видно в окружении
  const editable = may && card.confirmed && topic
  const inPlan = topic ? `/plan?course=${card.course.id}&row=${topic.id}` : null
  // раздел, в котором нечего показывать, рисуется одной строкой: пустота не
  // должна занимать столько же места, сколько содержимое
  const hasContent = topic && CONTENT.some((field) => topic[field])
  const hasHomework = Boolean(topic?.homework) || homework.length > 0

  const open = (kind) => {
    setForm(kind)
    setText(kind === 'rename' ? topic.title : '')
    setLink({ url: '', title: '' })
  }

  /**
   * Правка полей строки плана — прямо в блоке, который их показывает.
   *
   * Окном (`LessonPanel`, общим с таблицей плана) это было, и оттуда взялся
   * вопрос «куда я попал»: из плашки домашнего задания открывался редактор
   * **всех четырёх** полей. В таблице плана окно нужно — там строка в одну
   * линию, места нет; здесь блок и так карточка во всю ширину.
   */
  const editBlock = (fields) =>
    setEditing({
      fields,
      draft: Object.fromEntries(fields.map((name) => [name, topic[name] ?? ''])),
    })

  const fieldsForm = (
    <form
      className="lesson-edit"
      onSubmit={(event) => {
        event.preventDefault()
        run(async () => {
          await updatePlanNode(topic.id, editing.draft)
          setEditing(null)
        })
      }}
    >
      {editing?.fields.map((name) => (
        <label className="lesson-field" key={name}>
          <span className="hint">{t(`lesson.fields.${name}`)}</span>
          <textarea
            rows={name === 'body' ? 10 : 4}
            value={editing.draft[name]}
            placeholder={t(`lesson.placeholders.${name}`)}
            onChange={(event) =>
              setEditing((current) => ({
                ...current,
                draft: { ...current.draft, [name]: event.target.value },
              }))
            }
          />
        </label>
      ))}
      <div className="row">
        <button type="submit" disabled={busy}>
          {t('common.save')}
        </button>
        <button type="button" className="secondary" onClick={() => setEditing(null)}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )

  /** Кнопка правки блока — пока не правят соседний. */
  const editAction = (fields) =>
    editable &&
    !editing && (
      <button
        type="button"
        className="secondary compact"
        disabled={busy}
        onClick={() => editBlock(fields)}
      >
        {t('lessonScreen.edit')}
      </button>
    )

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

    // переименование — жёсткая правка: та же строка, сказанная точнее
    // («Синус суммы. Начало»). Меняется программа курса, и это осознанно
    run(() => updatePlanNode(topic.id, { title: value }))
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
        {/* ссылка в ряду кнопок — кнопкой: подчёркнутый текст между
            контролами читается как сбой вёрстки */}
        <Link to="/today" className="link-button">
          {t('lessonScreen.toDay')}
        </Link>
      </div>

      {/*
        Шапка отвечает на вопрос «какой это урок» целиком: когда и у кого,
        как называется, записан ли и где его править.

        Карточкой под заголовком состояние стояло, и это было лишним
        разрывом: плашка «урок проведён» относится к теме, написанной
        строкой выше, а не к чему-то, что идёт следом. Своей карточки под
        неё больше нет.

        Что было на уроке, решает **план**, поэтому здесь не выбор, а
        подтверждение: «раскладка предлагает вот это — так и было». Не
        угадала — правят план по ссылке рядом, и подсказка меняется сама.

        Записать можно только прошедшее: кнопка, нажатая накануне, стала бы
        ложью после утренней пожарной тревоги, и заметить это было бы
        некому.
      */}
      <header className="lesson-title-head">
        <p className="hint">
          {longDate(card.date)} ·{' '}
          {t('today.lessonNumber', { number: card.lesson_number })} ·{' '}
          {card.course.name}
        </p>

        {/* Переименование — кликом по названию, как в таблице плана: одна
            операция не должна делаться двумя разными способами на двух
            экранах. Кнопкой в ряду действий она стояла с тех пор, когда
            карточка приехала с «Сегодня», где заголовок был просто
            заголовком */}
        {form === 'rename' ? (
          <form className="row" onSubmit={submit}>
            <input
              autoFocus
              value={text}
              maxLength={200}
              aria-label={t('today.renameTitle')}
              placeholder={t('today.renameTitle')}
              onChange={(event) => setText(event.target.value)}
            />
            <button type="submit" disabled={busy}>
              {t('common.save')}
            </button>
            <button type="button" className="secondary" onClick={() => setForm(null)}>
              {t('common.cancel')}
            </button>
          </form>
        ) : (
          <div className="lesson-title-row">
            <h1>
              {editable ? (
                <button
                  type="button"
                  className="link name"
                  title={t('today.rename')}
                  disabled={busy}
                  onClick={() => open('rename')}
                >
                  {topic.title}
                </button>
              ) : (
                topic?.title ?? t('agenda.noTopic')
              )}
            </h1>

            <div className="lesson-state">
              {topic && (
                <>
                  {card.confirmed ? (
                  // повторное нажатие снимает — тем же приёмом, что отметка
                  // в журнале и вердикт в проверке работ. Без него исправить
                  // запись было бы нечем: «связать с другой строкой» больше
                  // не предлагается
                    may ? (
                      <button
                        type="button"
                        className="badge state good"
                        title={t('lessonScreen.withdrawHint')}
                        disabled={busy}
                        onClick={() =>
                          run(() => updateSlot(card.id, { lesson: null }))
                        }
                      >
                        {t('lessonScreen.recorded')}
                      </button>
                    ) : (
                      <span className="badge state good">
                        {t('lessonScreen.recorded')}
                      </span>
                    )
                  ) : (
                    may &&
                    done && (
                      <button
                        type="button"
                        className="secondary compact"
                        disabled={busy}
                        onClick={() =>
                          run(() => updateSlot(card.id, { lesson: topic.id }))
                        }
                      >
                        {t('lessonScreen.bind')}
                      </button>
                    )
                  )}

                  <Link className="link-button" to={inPlan}>
                    {t('lessonScreen.openInPlan')}
                  </Link>
                </>
              )}

              {/* Действия над самим занятием — редкие и разрушительные.
                  Кнопкой в потоке страницы отмена стояла последним пунктом
                  и читалась как шаг урока. Меню стоит вне ветки темы:
                  занятие без строки плана отменяют так же */}
              {may && (
                <div className="lesson-menu" ref={menuRef}>
                  <button
                    type="button"
                    className="link more"
                    aria-haspopup="true"
                    aria-expanded={menuOpen}
                    aria-label={t('lessonScreen.more')}
                    title={t('lessonScreen.more')}
                    onClick={() => setMenuOpen(!menuOpen)}
                  >
                    ⋯
                  </button>
                  {menuOpen && (
                    <div className="dropdown">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          closeMenu()
                          if (card.is_cancelled)
                            run(() =>
                              updateSlot(card.id, { is_cancelled: false, reason: '' }),
                            )
                          else open('cancel')
                        }}
                      >
                        {t(
                          card.is_cancelled
                            ? 'lessonScreen.restoreLesson'
                            : 'lessonScreen.cancelLesson',
                        )}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Пустое место на месте пропавших кнопок читалось бы как поломка,
            поэтому запрет объясняется словами и сразу даёт выход */}
        {!topic ? (
          <p className="hint">{t('today.noTopic')}</p>
        ) : (
          !card.confirmed && <p className="hint">{t('lessonScreen.planOwns')}</p>
        )}
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {card.is_cancelled && (
        <p className="hint warning">
          {t('today.cancelled')}
          {card.reason && `: ${card.reason}`}
        </p>
      )}

      {/*
        Пять блоков одной колонкой.

        Обёртка нужна не для вида, а чтобы адресовать наведение: действия
        разделов появляются под курсором, как кнопки строки в таблице плана.
        Шаг она задаёт сама — иначе пять карточек стали бы одним ребёнком
        `.page` и слиплись бы.
      */}
      <div className="lesson-blocks">
      {/* 1. Кто пришёл — это делают до того, как начали. Карточку рисует
          сам блок: заголовок у него кликабельный, и жить он должен вместе
          со своей свёрнутостью */}
      <LessonAttendance slotId={card.id} may={may} onError={handleError} />

      {/* 2. Чем занимаемся. Правится здесь же, прямо в блоке: кнопка,
          живущая в другой карточке, не находится, а окно поверх страницы
          отвечало на вопрос «куда я попал» */}
      <Collapsible
        name="content"
        title={t('lessonScreen.content')}
        empty={!hasContent && editing?.fields !== CONTENT}
        note={hasContent ? null : t('lessonScreen.blank')}
        actions={editAction(CONTENT)}
      >
        {editing?.fields === CONTENT ? (
          fieldsForm
        ) : (
          CONTENT.filter((field) => topic[field]).map((field) => (
            <div className="lesson-field" key={field}>
              <span className="hint">{t(`lesson.fields.${field}`)}</span>
              <Markdown text={topic[field]} />
            </div>
          ))
        )}
      </Collapsible>

      {/* 3. Что решаем */}
      <Collapsible
        name="works"
        title={t('lessonScreen.works')}
        empty={!classwork.length}
        note={classwork.length || t('lessonScreen.none')}
        actions={
          may && (
            <button
              type="button"
              className="secondary compact"
              disabled={busy}
              onClick={() => setAdding('work')}
            >
              {t('lessonScreen.newWork')}
            </button>
          )
        }
      >
        {classwork.length > 0 && (
          <ul className="work-links">
            {classwork.map((work) => (
              <li key={work.id}>
                <Link to={`/works/${work.id}`}>{work.title}</Link>
                <span className={`badge state-${work.state}`}>
                  {t(`works.state.${work.state}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Collapsible>

      {/* 4. Чем пользуемся: файлы и ссылки строки плана */}
      <Collapsible
        name="materials"
        title={t('lessonScreen.materials')}
        empty={!topic?.attachments?.length && form !== 'link'}
        note={topic?.attachments?.length || t('lessonScreen.none')}
        actions={
          editable && (
            <>
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => open('link')}
              >
                {t('lessonScreen.addLink')}
              </button>
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                {t('lesson.addFile')}
              </button>
              {/* нативный input прячется: его подпись браузер рисует сам,
                  на своём языке и своей кнопкой */}
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
            </>
          )
        }
      >
        {topic?.attachments?.length > 0 && (
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
                {editable && (
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

        {editable && form === 'link' && (
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
        )}
      </Collapsible>

      {/* 5. Что задаём на дом — последним, потому что объявляют его в конце */}
      <Collapsible
        name="homework"
        title={t('lessonScreen.homework')}
        empty={!hasHomework && editing?.fields !== HOMEWORK}
        note={homework.length || t('lessonScreen.none')}
        actions={
          may && (
            <>
              {editAction(HOMEWORK)}
              <button
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => setAdding('homework')}
              >
                {t('lessonScreen.newHomework')}
              </button>
            </>
          )
        }
      >
        {/* Два разных ответа, и оба нужны. В плане написано, **что обычно
            задают** по этой теме, — это программа, она уезжает в библиотеку
            и на следующий год. Ниже — что задали **этому классу в этот
            день**: та же работа, что в разделе выше, просто вынесенная
            сюда. Копировать одно в другое мы не стали: подставленный текст
            здесь уже был и оказался не нужен. */}
        {editing?.fields === HOMEWORK ? (
          fieldsForm
        ) : (
          topic?.homework && <Markdown text={topic.homework} />
        )}

        {homework.length > 0 && (
          <ul className="work-links">
            {homework.map((work) => (
              <li key={work.id}>
                <Link to={`/works/${work.id}`}>{work.title}</Link>
                <span className={`badge state-${work.state}`}>
                  {t(`works.state.${work.state}`)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Collapsible>

      </div>

      {/* Причина отмены — формой на месте кнопки, а не в меню: меню
          закрывается по клику мимо, и поле ввода в нём жило бы до первого
          промаха */}
      {may && form === 'cancel' && (
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
      )}

      {adding && (
        <WorkDialog
          courseId={card.course.id}
          slot={card.id}
          homework={adding === 'homework'}
          busy={busy}
          onSubmit={(fields) =>
            run(async () => {
              await createWork(fields)
              setAdding(null)
            })
          }
          onClose={() => setAdding(null)}
        />
      )}

    </main>
  )
}
