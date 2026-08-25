import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import EmptyState from './EmptyState'
import { dateTime } from './dates'
import { fetchTalk, fetchTalks, sendTalkMessage } from './api'
import { POLL_MS } from './polling'

/**
 * Переписка: список собеседников слева, разговор справа, строка отправки внизу.
 *
 * **Один экран на всех**, и это не экономия. Собеседник не меняет природы
 * разговора: коллега, ученик, родитель — одна вещь функционально, и три экрана
 * под неё означали бы три места, где искать сказанное. Так уже было: разговор
 * родителя с учителем жил своим экраном, смонтированным только у родителя, и
 * учитель не мог ни прочитать сообщение, ни ответить — при том, что сервер
 * отвечал обеим сторонам.
 *
 * **Лента складывается по собеседнику, а не по поводу.** Вопрос ученика о
 * задаче и ответ ему же «зайди после урока» — один разговор; у первой реплики
 * есть ссылка на задачу, у второй нет, и это единственная разница, которую
 * человек тут видит.
 *
 * Своей страницы у разговора нет — адрес один на весь мессенджер. Открытый
 * собеседник это поза за работой, а не место, на которое ссылаются: ссылку на
 * переписку никому не дают.
 */
export default function Messenger({ onLoggedOut }) {
  const { t } = useTranslation()

  const [list, setList] = useState(null)
  const [open, setOpen] = useState(null) // id собеседника
  const [talk, setTalk] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const bottom = useRef(null)

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) onLoggedOut()
      else setError(err.message)
    },
    [onLoggedOut],
  )

  const loadList = useCallback(
    () => fetchTalks().then(setList).catch(handleError),
    [handleError],
  )

  useEffect(() => {
    loadList()
  }, [loadList])

  /* Разговор перечитывается опросом: собеседник пишет, пока экран открыт, и
     ждать от человека F5 значит показывать ему устаревшую переписку. */
  useEffect(() => {
    if (open === null) return undefined

    let alive = true
    const pull = () =>
      fetchTalk(open)
        .then((answer) => alive && setTalk(answer))
        .catch(() => {})

    pull()
    const timer = setInterval(() => {
      pull()
      loadList()
    }, POLL_MS)

    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [open, loadList])

  /* Лента прокручивается к последнему: разговор читают с конца. */
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'nearest' })
  }, [talk])

  const send = async () => {
    if (!text.trim() || open === null) return
    setBusy(true)
    setError(null)
    try {
      setTalk(await sendTalkMessage(open, text))
      setText('')
      await loadList()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  if (list === null) {
    return (
      <main className="page">
        <p>{error ? <span className="error">{error}</span> : t('common.loading')}</p>
      </main>
    )
  }

  const started = list.started ?? []
  const partners = list.partners ?? []
  /* Кому можно написать, но ещё не написали. Начатые уже стоят слева, и
     второй раз показывать их в выборе значит предлагать начать начатое. */
  const fresh = partners.filter(
    (person) => !started.some((row) => row.id === person.id),
  )
  const talking = started.find((row) => row.id === open)

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('talks.title')}</h1>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {started.length === 0 && fresh.length === 0 ? (
        <EmptyState title={t('talks.nobody.title')}>{t('talks.nobody.hint')}</EmptyState>
      ) : (
        <div className="chat">
          <ul className="chat-list">
            {started.map((person) => (
              <li key={person.id}>
                <button
                  type="button"
                  className={open === person.id ? 'chat-pick active' : 'chat-pick'}
                  onClick={() => setOpen(person.id)}
                >
                  <b>
                    {person.name}
                    {person.unread > 0 && (
                      <span className="unread">{person.unread}</span>
                    )}
                  </b>
                  {/* последняя реплика одной строкой: по ней разговор и
                      узнают в списке, а имя собеседника повторяется у всех */}
                  <span className="hint">
                    {person.last ? person.last.text : t('talks.nothingYet')}
                  </span>
                </button>
              </li>
            ))}

            {fresh.length > 0 && (
              <li className="chat-fresh">
                <span className="hint">{t('talks.writeTo')}</span>
                {fresh.map((person) => (
                  <button
                    key={person.id}
                    type="button"
                    className={open === person.id ? 'chat-pick active' : 'chat-pick'}
                    onClick={() => setOpen(person.id)}
                  >
                    <b>{person.name}</b>
                    <span className="hint">{t(`talks.kind.${person.kind}`)}</span>
                  </button>
                ))}
              </li>
            )}
          </ul>

          <section className="panel chat-thread">
            {open === null ? (
              <p className="hint">{t('talks.pickSomebody')}</p>
            ) : (
              <>
                <h3>{talk?.person?.name ?? talking?.name ?? ''}</h3>
                <ul className="chat-messages">
                  {(talk?.messages ?? []).map((message) => (
                    <li
                      key={message.id}
                      className={message.mine ? 'chat-message mine' : 'chat-message'}
                    >
                      <span className="hint">
                        {message.author_name} · {dateTime(message.at)}
                        {/* повод, если он есть: разговор о задаче ведётся
                            здесь же, и вернуться к работе надо одним
                            нажатием. Адрес один на обе стороны — у учителя
                            это проверка, у ученика его же работа */}
                        {message.work && (
                          <>
                            {' · '}
                            <Link to={`/works/${message.work}`} className="link">
                              {t('talks.aboutTask')}
                            </Link>
                          </>
                        )}
                      </span>
                      <p>{message.text}</p>
                    </li>
                  ))}
                  <li ref={bottom} />
                </ul>

                <div className="row">
                  <input
                    value={text}
                    aria-label={t('talks.message')}
                    placeholder={t('talks.message')}
                    disabled={busy}
                    onChange={(event) => setText(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && send()}
                  />
                  <button type="button" disabled={busy || !text.trim()} onClick={send}>
                    {t('talks.send')}
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
