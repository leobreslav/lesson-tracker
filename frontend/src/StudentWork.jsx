import { useCallback, useEffect, useRef, useState } from 'react'
import TaskThread from './TaskThread'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import Markdown from './Markdown'
import Statement from './Statement'
import { fetchStudentWork, openAttachment, sendAnswer } from './api'
import { dateTime } from './dates'
import { POLL_MS } from './polling'

/**
 * Решение работы: задачи одна под другой, ответ уходит по каждой отдельно.
 *
 * Не «отправить всё в конце»: браузер закроют, интернет отвалится, урок
 * кончится — и работа, отправляемая целиком, теряется вся. Отправленное же
 * лежит на сервере с той минуты, когда его написали.
 *
 * История попыток видна ученику полностью. Она у него и так есть — он сам
 * это писал, — а прятать её значило бы делать вид, что попытка стирает
 * прошлую: она её не стирает нигде, в том числе у учителя.
 *
 * Страница опрашивается так же, как таблица у учителя: отметка приходит
 * ученику без его участия, и обновлять её руками он не должен. Черновик в
 * поле ответа при этом цел — состояние ввода живёт в самой карточке задачи,
 * а перерисовка приходит сверху и его не касается.
 */
export default function StudentWork() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [work, setWork] = useState(null)
  const [error, setError] = useState(null)

  const version = useRef(null)

  const load = useCallback(
    async ({ polling = false } = {}) => {
      const answer = await fetchStudentWork(id, polling ? version.current : null)
      version.current = answer.version
      // «не изменилось» — не повод перерисовывать: лишний рендер посреди
      // набора ответа человеку ничего не сообщает
      if (answer.changed !== false) setWork(answer)
    },
    [id],
  )

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [load])

  useEffect(() => {
    const timer = setInterval(() => load({ polling: true }).catch(() => {}), POLL_MS)
    return () => clearInterval(timer)
  }, [load])

  const quiet = work && silence(work)

  if (work === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{work.title}</h1>
        <p className="hint">
          {work.course_name} · {t(`works.state.${work.state}`)} ·{' '}
          {dateTime(work.opens_at)} — {dateTime(work.closes_at)}
        </p>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {quiet && <p className="hint warning">{t(quiet)}</p>}

      {work.description && (
        <section className="panel">
          <Markdown text={work.description} />
        </section>
      )}

      <Grade work={work} />

      {/* «задач пока нет» — про работу, которую ещё не наполнили. Если
          молчание уже объяснено сверху, второй раз объяснять нечего */}
      {work.tasks.length === 0 && !quiet && (
        <p className="hint">{t('student.work.noTasks')}</p>
      )}

      {work.tasks.length > 0 && (
        <ol className="student-tasks">
          {work.tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              // имя вопроса, а не его место в списке: учитель говорит на уроке
              // «второй пункт первой задачи», и на экране ученик должен найти
              // «1б». Пока номер считался здесь, переименование до ученика не
              // доезжало вовсе — и два экрана называли один вопрос по-разному
              number={task.name}
              canAnswer={work.can_answer}
              onSent={load}
              onError={setError}
            />
          ))}
        </ol>
      )}

      <p>
        <Link to="/">{t('student.title')}</Link>
      </p>
    </main>
  )
}

/*
 * Почему в этой работе нельзя отвечать — или `null`, если можно.
 *
 * Причин три, и они разные: окно закрылось, его сняли с курса, вопросы
 * решают на бумаге. Раньше их было две, и различал их `work.state`; третью
 * знал флаг работы (`on_paper`), а теперь она складывается из самих ячеек —
 * ни одна не принимает ответы.
 *
 * Пустая работа молчит: «задач пока нет» стоит на месте списка и говорит всё.
 */
const silence = (work) => {
  if (work.can_answer) return null
  if (work.state === 'closed') return 'student.work.closed'
  if (!work.enrolled) return 'student.work.readonly'

  // отвечать негде — но это ещё не значит «на бумаге»: работу могли просто
  // не наполнить. Различает их то, есть ли тут вообще что-нибудь его: ячейки
  // или его собственный скан. Пустая работа без скана молчит, и за неё
  // говорит «задач пока нет» на месте списка.
  const papers = work.papers ?? []
  return work.tasks.length > 0 || papers.length > 0 ? 'paper.onPaper' : null
}

/**
 * Оценка и слова учителя — над задачами, потому что за этим и приходят.
 *
 * Пока работа не оценена, плашки нет вовсе: «ещё не оценено» на пустом
 * месте читается как обещание, которого никто не давал. А вот шкалу, если
 * она есть, показываем всегда — «из пяти» это про работу, а не про него.
 *
 * Комментарий живёт без оценки: работа может не оцениваться, а сказать о
 * ней есть что.
 */
function Grade({ work }) {
  const { t } = useTranslation()
  const criteria = work.criteria ?? []
  const marks = work.marks ?? {}
  const papers = work.papers ?? []
  const given = criteria.some((item) => marks[item.id] !== undefined)

  if (!given && !work.comment && !papers.length) return null

  return (
    <section className="panel student-grade">
      {papers.length > 0 && (
        <ul className="attachments">
          {papers.map((paper) => (
            <li key={paper.id} className="attachment">
              <span className="attachment-icon" aria-hidden="true">
                📄
              </span>
              {paper.kind === 'link' ? (
                <a href={paper.url} target="_blank" rel="noreferrer" className="title">
                  {paper.title}
                </a>
              ) : (
                <button
                  type="button"
                  className="link title"
                  onClick={() => openAttachment(paper.id)}
                >
                  {paper.title}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {given && (
        <ul className="marks">
          {criteria.map((item) => (
            <li key={item.id}>
              {item.name && <span className="hint">{item.name}</span>}
              <b>
                {marks[item.id] ?? '–'}
                <span className="hint"> / {item.maximum}</span>
              </b>
            </li>
          ))}
        </ul>
      )}
      {work.comment && <p className="comment">{work.comment}</p>}
    </section>
  )
}

/**
 * Одна задача: условие, поле ответа и то, что уже отправлено.
 *
 * Черновик здесь не нужен и его нет: пока ответ не отправлен, он не
 * существует ни для кого. Кнопка одна, и после неё в истории появляется
 * строка — это и есть подтверждение, что ответ ушёл.
 */
function TaskCard({ task, number, canAnswer, onSent, onError }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  // ответить можно, когда открыты **и** работа, и сама ячейка: закрытая
  // ячейка — это «решайте на листе», а не запрет
  const open = canAnswer && task.open_for_answers
  const out = task.attempts_left === 0
  const send = async (event) => {
    event.preventDefault()
    if (busy || !text.trim()) return

    setBusy(true)
    try {
      await sendAnswer(task.id, text)
      setText('')
      await onSent()
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    // номер рисует CSS из `data-number`, а не счётчик списка: счётчик умеет
    // считать только по порядку, а вопрос зовётся так, как его назвали
    <li className="panel student-task" data-number={number}>
      <div className="task-question">
        {/* пункт показывается вместе со своим сюжетом — или без него, если
            учитель шапку выключил: данные он написал на доске */}
        <Statement shown={task.shown} />
        {/* «вы это уже решали» — факт, но без старого ответа: он живёт в той
            работе и показывается по её правилам */}
        {task.seen_before?.length > 0 && (
          <p className="hint">
            {t('student.seenBefore', {
              title: task.seen_before[0].title,
            })}
          </p>
        )}
      </div>

      {task.submissions.length > 0 && (
        <ul className="attempt-list">
          {task.submissions.map((submission, index) => (
            <li key={submission.id} className={verdictClass(submission.mark, task.maximum)}>
              <div className="cells">
                <span className="attempt">
                  {t('student.work.attemptNumber', { number: index + 1 })}
                </span>
                <span className="answer">{submission.answer}</span>
                <span className="hint">{dateTime(submission.created_at)}</span>
                <span className="verdict">
                  {verdictLabel(submission.mark, task.maximum, t)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {open && !out && (
        <form className="row" onSubmit={send}>
          <input
            value={text}
            disabled={busy}
            placeholder={t('student.work.answer')}
            aria-label={t('student.work.answerNumber', { number })}
            onChange={(event) => setText(event.target.value)}
          />
          <button type="submit" disabled={busy || !text.trim()}>
            {t('student.work.send')}
          </button>
          {task.attempts_left !== null && (
            <span className="hint">
              {t('student.work.attemptsLeft', { count: task.attempts_left })}
            </span>
          )}
        </form>
      )}

      {open && out && (
        <p className="hint warning">{t('student.work.noAttempts')}</p>
      )}

      {/* работа принимает ответы, а этот вопрос нет: значит его сдают на
          листе. У работы, где на бумаге всё, это сказано один раз сверху */}
      {canAnswer && !task.open_for_answers && (
        <p className="hint">{t('student.work.onPaperQuestion')}</p>
      )}

      {/* спросить учителя можно прямо тут: вопрос про эту задачу, а не про
          работу вообще, и тред у них с учителем один и тот же */}
      <TaskThread task={task.id} student={null} me={null} />
    </li>
  )
}

/*
 * Балл за ответ глазами ученика.
 *
 * У вопроса из одного балла это по-прежнему «верно» и «неверно» — слова, а
 * не цифры: «1 из 1» ученику не говорит ничего. Там, где баллов больше,
 * показывается дробь: «2 из 3» и есть ответ на «как меня проверили».
 */
const verdictClass = (mark, maximum) => {
  if (mark === null || mark === undefined) return 'unchecked'
  if (mark >= maximum) return 'correct'
  return mark === 0 ? 'wrong' : 'partial'
}

const verdictLabel = (mark, maximum, t) => {
  if (mark === null || mark === undefined) return t('student.work.unchecked')
  if (maximum === 1) {
    return t(mark >= 1 ? 'student.work.correct' : 'student.work.wrong')
  }
  return t('student.work.scored', { mark, maximum })
}
