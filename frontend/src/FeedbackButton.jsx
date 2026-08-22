import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import Switch from './Switch'
import { sendFeedback } from './api'

/**
 * «Сказать разработчику» — кнопка в баре и окно за ней.
 *
 * Стоит в баре у **обоих** интерфейсов, и это главное решение здесь. Ученик
 * видит те же поломки, что учитель, а сказать о них ему было нечем вовсе:
 * администратор школы не чинит интерфейс, а больше писать некому. Молчащий
 * пользователь выглядит как довольный ровно до того дня, когда перестаёт
 * заходить.
 *
 * Полей два — вид и текст, — и это тоже решение, а не заготовка. Форма
 * баг-репорта («что нажали», «что ожидали», «браузер») — инструмент для
 * того, кто умеет их писать; здесь пишут учителя между уроками, и пустая
 * форма из шести полей отпугнёт вернее любой сложности. Всё, что можно
 * узнать не спрашивая, узнаётся не спрашивая: адрес страницы, кто, когда и
 * из какой школы проставляет сервер.
 *
 * Отправленное не показывается отправившему, и переписки тут нет: обращение
 * — не заявка в поддержку, ответом на него будет починка. Обещать ответ,
 * которого один человек на всех дать не может, хуже, чем не обещать.
 */
export default function FeedbackButton({ compact = false }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        className="secondary feedback-open"
        title={t('feedback.title')}
        onClick={() => setOpen(true)}
      >
        {/* на узком экране и в баре ученика — один значок: место в баре
            дороже слова, а значок с подписью в title читается наведением */}
        <span aria-hidden="true">✉</span>
        {!compact && <span className="feedback-word">{t('feedback.open')}</span>}
      </button>

      {open && <FeedbackDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function FeedbackDialog({ onClose }) {
  const { t } = useTranslation()
  const [kind, setKind] = useState('bug')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    if (!text.trim()) return

    setBusy(true)
    setError(null)
    try {
      await sendFeedback({
        kind,
        text,
        // откуда написали. Половина сообщений об ошибке — «тут ничего не
        // работает», и без адреса страницы искать это негде
        page: window.location.pathname + window.location.search,
      })
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      /* кнопки «Закрыть» тут нет намеренно: она ничего не решает, а просто
         уводит — уводят отсюда крестик, Escape и клик мимо */
      <Modal onClose={onClose} title={t('feedback.thanksTitle')}>
        <p className="hint">{t('feedback.thanks')}</p>
      </Modal>
    )
  }

  return (
    <Modal onClose={onClose} title={t('feedback.title')}>
      <form onSubmit={submit}>
        <p className="hint">{t('feedback.hint')}</p>

        <Switch
          label={t('feedback.kind')}
          value={kind}
          onChange={setKind}
          disabled={busy}
          options={[
            { value: 'bug', label: t('feedback.bug') },
            { value: 'idea', label: t('feedback.idea') },
          ]}
        />

        <label>
          {t('feedback.text')}
          <textarea
            autoFocus
            rows={6}
            maxLength={4000}
            value={text}
            disabled={busy}
            placeholder={t(kind === 'bug' ? 'feedback.bugHint' : 'feedback.ideaHint')}
            onChange={(event) => setText(event.target.value)}
          />
        </label>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !text.trim()}>
            {t('feedback.send')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
