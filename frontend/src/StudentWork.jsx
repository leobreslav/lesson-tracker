import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import Markdown from './Markdown'
import { fetchStudentWork, sendAnswer } from './api'
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

      {!work.can_answer && (
        <p className="hint warning">
          {t(work.state === 'closed' ? 'student.work.closed' : 'student.work.readonly')}
        </p>
      )}

      {work.tasks.length === 0 ? (
        <p className="hint">{t('student.work.noTasks')}</p>
      ) : (
        <ol className="student-tasks">
          {work.tasks.map((task, index) => (
            <TaskCard
              key={task.id}
              task={task}
              number={index + 1}
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
    <li className="panel student-task">
      <div className="task-question">
        <Markdown text={task.question} />
      </div>

      {task.submissions.length > 0 && (
        <ul className="attempt-list">
          {task.submissions.map((submission, index) => (
            <li key={submission.id} className={verdictClass(submission.verdict)}>
              <span className="attempt">
                {t('student.work.attemptNumber', { number: index + 1 })}
              </span>
              <span className="answer">{submission.answer}</span>
              <span className="hint">{dateTime(submission.created_at)}</span>
              <span className="verdict">{verdictLabel(submission.verdict, t)}</span>
            </li>
          ))}
        </ul>
      )}

      {canAnswer && !out && (
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

      {canAnswer && out && (
        <p className="hint warning">{t('student.work.noAttempts')}</p>
      )}
    </li>
  )
}

const verdictClass = (verdict) =>
  verdict === true ? 'correct' : verdict === false ? 'wrong' : 'unchecked'

const verdictLabel = (verdict, t) =>
  t(
    verdict === true
      ? 'student.work.correct'
      : verdict === false
        ? 'student.work.wrong'
        : 'student.work.unchecked',
  )
