import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { fetchThread, sendToThread } from './api'
import { dateTime } from './dates'

/**
 * Разговор о задаче: ученик спрашивает, учитель отвечает.
 *
 * Компонент один на обе стороны, и это не экономия строк: тред у них
 * **общий**, а два разных экрана над одними данными разъезжаются в первую же
 * правку. Учитель открывает его из проверки, ученик — со своей страницы
 * задачи, и видят они одно и то же.
 *
 * Чата пока нет; когда появится, он будет читать эти же треды, сгруппированные
 * по собеседнику, — поэтому предмет треда пара «задача и ученик», а не
 * «переписка двоих».
 */
export default function TaskThread({ task, student, me }) {
  const { t } = useTranslation()
  const [thread, setThread] = useState(null)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    fetchThread(task, student)
      .then((answer) => alive && setThread(answer))
      .catch((problem) => alive && setError(problem.message))
    return () => {
      alive = false
    }
  }, [task, student])

  const send = async () => {
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      setThread(await sendToThread(task, student, text))
      setText('')
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!thread) return null

  /* Свёрнут, пока говорить не о чем. Поле ввода в каждой задаче — шум: их на
     странице десять, а спрашивают про одну. Есть сообщения — разговор открыт
     сам: учитель обязан увидеть вопрос, не открывая каждую задачу. */
  const said = thread.messages.length
  if (!open && !said) {
    return (
      <p className="hint task-thread">
        <button type="button" className="link" onClick={() => setOpen(true)}>
          {t('thread.ask')}
        </button>
      </p>
    )
  }

  return (
    <section className="task-thread">
      <h4>{t('thread.title')}</h4>
      {error && <p className="error">{error}</p>}

      {thread.messages.length === 0 ? (
        <p className="hint">{t('thread.none')}</p>
      ) : (
        <ul className="thread-list">
          {thread.messages.map((message) => (
            <li key={message.id} className={message.author === me ? 'mine' : ''}>
              <span className="who">{message.author_name || t('thread.somebody')}</span>
              <span className="said">{message.text}</span>
              {/* у сообщения полная метка времени, а не дата: `shortDate`
                  ждёт «ГГГГ-ММ-ДД» и на метке падает */}
              <span className="hint when">{dateTime(message.at)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="row">
        <input
          value={text}
          disabled={busy}
          placeholder={t('thread.placeholder')}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') send()
          }}
        />
        <button type="button" disabled={busy || !text.trim()} onClick={send}>
          {t('thread.send')}
        </button>
      </div>
    </section>
  )
}
