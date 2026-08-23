import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { removePhotoNote, sayInPhotoNote } from './api'
import { dateTime } from './dates'

/**
 * Разговор о месте на фотографии.
 *
 * Не окно поверх окна, а полоса под снимком, и это решение: вопрос «что тут
 * не так» задают, **глядя на это место**, — спрячь снимок вторым диалогом, и
 * отвечать придётся по памяти. Заодно снимается непонятный Escape, который
 * закрывал бы то ли разговор, то ли просмотрщик.
 *
 * Компонент один на две стороны — как `TaskThread` у разговора о задаче, и по
 * той же причине: тред у них общий, а два экрана над одними данными
 * разъезжаются в первую же правку.
 *
 * Новая булавка отличается от открытой ровно тем, что у неё ещё нет первого
 * слова: `note` пуст, и вместо ленты стоит поле. Булавка без слов не
 * заводится вовсе (`works.photos.pin`) — точка на картинке, которую некому
 * объяснить, читается учеником как пустой кружок.
 */
export default function PhotoNoteThread({
  note,
  busy,
  mayRemove,
  onPin,
  onSaid,
  onRemoved,
  onClose,
}) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  const send = async () => {
    if (!text.trim() || sending) return

    setSending(true)
    setError(null)
    try {
      if (note) onSaid(await sayInPhotoNote(note.id, text))
      else await onPin(text)
      setText('')
    } catch (problem) {
      setError(problem.message)
    } finally {
      setSending(false)
    }
  }

  const drop = async () => {
    setError(null)
    try {
      await removePhotoNote(note.id)
      onRemoved(note.id)
    } catch (problem) {
      setError(problem.message)
    }
  }

  return (
    <section className="photo-note">
      <div className="panel-head spread">
        <h4>{note ? t('photos.noteTitle') : t('photos.newNote')}</h4>
        <span>
          {note && mayRemove && (
            <button type="button" className="link" onClick={drop}>
              {t('common.delete')}
            </button>
          )}{' '}
          <button type="button" className="link" onClick={onClose}>
            ✕
          </button>
        </span>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {note && (
        <ul className="thread-list">
          {note.messages.map((message) => (
            <li key={message.id}>
              <span className="who">
                {message.author_name || t('thread.somebody')}
              </span>
              <span className="said">{message.text}</span>
              <span className="hint when">{dateTime(message.at)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="row">
        <input
          value={text}
          disabled={busy || sending}
          autoFocus={!note}
          placeholder={note ? t('thread.placeholder') : t('photos.notePlaceholder')}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') send()
          }}
        />
        <button
          type="button"
          disabled={busy || sending || !text.trim()}
          onClick={send}
        >
          {note ? t('thread.send') : t('photos.pinIt')}
        </button>
      </div>
    </section>
  )
}
