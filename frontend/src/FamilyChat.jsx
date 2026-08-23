import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import EmptyState from './EmptyState'
import { dateTime } from './dates'
import {
  fetchChildTeachers,
  fetchFamilyThreads,
  sendFamilyMessage,
  startFamilyThread,
} from './api'

/**
 * Разговор родителя с учителем.
 *
 * Один экран на обе стороны по построению: адрес `/api/family/threads/`
 * отвечает и родителю, и учителю, а кто из них смотрит — видно по
 * собственным сообщениям. Второй экран «для учителя» разошёлся бы с этим в
 * первой же правке; так уже было с выборками курсов.
 *
 * Список слева, разговор справа — обычная почта. Свежие треды сверху:
 * отвечают на последнее, а не на первое.
 *
 * **Начинает разговор родитель.** Список собеседников — ведущие курсов, где
 * ребёнок учится сейчас; писать всем сотрудникам школы он не может, и это не
 * ограничение ради ограничения: справочник вместо списка собеседников
 * означал бы, что учителю пишут по поводу, к нему не относящемуся.
 */
export default function FamilyChat({ user, onLoggedOut }) {
  const { t } = useTranslation()
  const [threads, setThreads] = useState(null)
  const [teachers, setTeachers] = useState([])
  const [open, setOpen] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const load = useCallback(
    () =>
      fetchFamilyThreads()
        .then((answer) => {
          setThreads(answer.threads)
          setOpen((current) =>
            current
              ? answer.threads.find((one) => one.id === current.id) ?? current
              : answer.threads[0] ?? null,
          )
        })
        .catch(handleError),
    [handleError],
  )

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (user.kind !== 'parent') return
    // список собеседников нужен только родителю: учитель разговор не заводит,
    // он на него отвечает
    fetchChildTeachers()
      .then((answer) => setTeachers(answer.teachers))
      .catch(() => setTeachers([]))
  }, [user.kind])

  const send = async () => {
    if (!text.trim() || !open) return
    setBusy(true)
    setError(null)
    try {
      await sendFamilyMessage(open.id, text)
      setText('')
      await load()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  const startWith = async (teacher) => {
    setBusy(true)
    setError(null)
    try {
      const thread = await startFamilyThread({ teacher })
      await load()
      setOpen(thread)
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  if (threads === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('parent.chat')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {user.kind === 'parent' && teachers.length > 0 && (
        <section className="panel">
          <p className="hint">{t('parent.writeTo')}</p>
          <div className="row">
            {teachers.map((teacher) => (
              <button
                key={teacher.id}
                type="button"
                className="secondary compact"
                disabled={busy}
                onClick={() => startWith(teacher.id)}
              >
                {teacher.name}
              </button>
            ))}
          </div>
        </section>
      )}

      {threads.length === 0 ? (
        <EmptyState title={t('parent.noThreads.title')}>
          {t('parent.noThreads.hint')}
        </EmptyState>
      ) : (
        <div className="chat">
          <ul className="chat-list">
            {threads.map((thread) => (
              <li key={thread.id}>
                <button
                  type="button"
                  className={
                    open && open.id === thread.id ? 'chat-pick active' : 'chat-pick'
                  }
                  onClick={() => setOpen(thread)}
                >
                  <b>
                    {user.kind === 'parent'
                      ? thread.teacher.name
                      : thread.parent.name}
                  </b>
                  <span className="hint">
                    {t('parent.about', { name: thread.child.name })}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <section className="panel chat-thread">
            {open && (
              <>
                <ul className="chat-messages">
                  {open.messages.map((message) => (
                    <li
                      key={message.id}
                      className={message.mine ? 'chat-message mine' : 'chat-message'}
                    >
                      <span className="hint">
                        {message.author.name} · {dateTime(message.created_at)}
                      </span>
                      <p>{message.text}</p>
                    </li>
                  ))}
                </ul>

                <div className="row">
                  <input
                    value={text}
                    aria-label={t('parent.message')}
                    placeholder={t('parent.message')}
                    disabled={busy}
                    onChange={(event) => setText(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && send()}
                  />
                  <button type="button" disabled={busy || !text.trim()} onClick={send}>
                    {t('parent.send')}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </main>
  )
}
