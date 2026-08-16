import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import DebtsDialog from './DebtsDialog'
import Modal from './Modal'
import EmptyState from './EmptyState'
import Markdown from './Markdown'
import {
  fetchCourses,
  fetchSlotDay,
  fetchUnclosed,
  updateSlot,
} from './api'
import { today } from './calendarLogic'
import { longDate } from './dates'

/**
 * День учителя одним экраном.
 *
 * Так он и выглядит: пришёл утром, посмотрел, что сегодня, провёл занятие
 * глядя в план, объявил практику, задал домашнее. Раньше это было четыре
 * экрана, и между ними приходилось помнить, где ты.
 *
 * **День показан сеткой, а не списком.** Список карточек отвечал только на
 * «какие занятия есть», а спрашивают утром другое — «как устроен день»: с
 * какого урока начинается, где окна, когда кончается. Окно в списке не
 * видно вовсе, потому что его в нём нет: пустое место нельзя показать
 * перечислением непустых.
 *
 * Поэтому слева столбец часов от первого до последнего занятого, а справа —
 * то занятие, которое выбрали. Чипы курсов при этом ушли: они выбирали, что
 * показать, а теперь день показан целиком, и выбирает клик по клетке.
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
  const [picked, setPicked] = useState(null) // выбранное занятие дня
  const [date, setDate] = useState(today())
  const [day, setDay] = useState(null)
  const [busy, setBusy] = useState(false)
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

  // Выбранного по умолчанию нет: предпросмотр — это окно, и открываться оно
  // должно от клика, а не от того, что человек долистал до дня с занятиями.
  // Выбор от прошлого дня тем более чужой.
  useEffect(() => {
    setPicked(null)
  }, [date])

  const run = async (request) => {
    setBusy(true)
    setError(null)
    try {
      await request()
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
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

  const lessons = day?.lessons ?? []
  // подтверждать можно только то, что уже случилось
  const done = day ? day.date <= today() : false
  const chosen = lessons.find((slot) => slot.id === picked) ?? null

  // Часы от первого до последнего занятого. Не «всегда с первого по
  // десятый»: пустые хвосты снизу и сверху — это не окна, это просто конец
  // дня, и рисовать их значит топить настоящие окна в шуме.
  const last = lessons.reduce((top, slot) => Math.max(top, slot.lesson_number), 0)
  const hours = Array.from({ length: last }, (_, index) => ({
    number: index + 1,
    // одно окно держит несколько занятий: отменённое места не занимает, и
    // рядом с ним законно стоит урок другого курса
    slots: lessons.filter((slot) => slot.lesson_number === index + 1),
  }))

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('today.title')}</h1>
      </header>

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

          {lessons.length === 0 ? (
            <p className="hint">{t('today.noLesson')}</p>
          ) : (
            <DayGrid hours={hours} picked={picked} onPick={setPicked} />
          )}
        </>
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

      {chosen && (
        <SlotPreview
          slot={chosen}
          busy={busy}
          done={done}
          onConfirm={() => run(() => updateSlot(chosen.id, { lesson: chosen.topic.id }))}
          onClose={() => setPicked(null)}
        />
      )}
    </main>
  )
}

/**
 * Столбец часов: где занятия, а где окна.
 *
 * Ради окон сетка и заведена. В списке карточек их нет — пустое место
 * нельзя показать перечислением непустых, — а утренний вопрос «как устроен
 * день» это в первую очередь про них: во сколько начинаю, где дыра, когда
 * свободен.
 *
 * Часы идут от первого до последнего занятого. Пустой хвост снизу — это не
 * окно, а конец дня, и рисовать его значит топить настоящие окна в шуме.
 *
 * В одном часу бывает несколько занятий: отменённое места не занимает, и
 * рядом с ним законно стоит урок другого курса. Поэтому клетка — список, а
 * не одно значение.
 */
function DayGrid({ hours, picked, onPick }) {
  const { t } = useTranslation()

  return (
    <ol className="day-grid">
      {hours.map(({ number, slots }) => (
        <li key={number} className={slots.length ? '' : 'empty'} data-hour={number}>
          <span className="hour">{number}</span>

          {slots.length === 0 ? (
            <span className="window">{t('today.window')}</span>
          ) : (
            <span className="taken">
              {slots.map((slot) => (
                <button
                  type="button"
                  key={slot.id}
                  data-slot={slot.id}
                  aria-pressed={slot.id === picked}
                  className={
                    'slot' +
                    (slot.id === picked ? ' picked' : '') +
                    (slot.is_cancelled ? ' cancelled' : '') +
                    (slot.is_extra ? ' extra' : '')
                  }
                  onClick={() => onPick(slot.id)}
                >
                  <span className="course">{slot.course.name}</span>
                  <span className="topic">
                    {/* короткая пометка, а не фраза из карточки: колонка
                        узкая, и целое предложение в ней всё равно обрежется
                        многоточием на втором слове */}
                    {slot.topic ? slot.topic.title : t('agenda.noTopic')}
                  </span>
                  {/* подтверждённое помечается: по столбцу видно, докуда
                      день закрыт, и это ровно то, чего не хватало списку */}
                  {slot.confirmed && <span className="done">✓</span>}
                </button>
              ))}
            </span>
          )}
        </li>
      ))}
    </ol>
  )
}




/**
 * Окно предпросмотра: что за занятие и что с ним можно сделать сейчас.
 *
 * Предпросмотр, а не карточка целиком: содержание урока со всеми четырьмя
 * полями — это уже работа, и для неё есть своя страница. Здесь ровно
 * столько, чтобы понять, туда ли попал, плюс действие, ради которого не
 * стоит уходить со дня: отметить, что занятие прошло.
 *
 * Главная кнопка — «Открыть урок». День отвечает на вопрос «что сегодня», а
 * работают с уроком на его собственной странице, и попасть туда надо
 * одинаково просто для прошлого, сегодняшнего и будущего.
 */
function SlotPreview({ slot, busy, done, onConfirm, onClose }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const topic = slot.topic

  return (
    <Modal onClose={onClose} title={topic ? topic.title : t('agenda.noTopic')}>
      <p className="hint">
        {t('today.lessonNumber', { number: slot.lesson_number })} · {slot.course.name}
      </p>

      {slot.is_cancelled ? (
        <p className="hint warning">
          {t('today.cancelled')}
          {slot.reason && `: ${slot.reason}`}
        </p>
      ) : (
        topic && (
          <p className="hint">
            {slot.confirmed ? t('lessonScreen.recorded') : t('today.suggested')}
          </p>
        )
      )}

      {slot.works.length > 0 && (
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
      )}

      <div className="actions">
        <button type="button" onClick={() => navigate(`/lesson/${slot.id}`)}>
          {t('today.openLesson')}
        </button>
        {topic && done && !slot.confirmed && !slot.is_cancelled && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onConfirm}
          >
            {t('today.confirm')}
          </button>
        )}
      </div>
    </Modal>
  )
}
