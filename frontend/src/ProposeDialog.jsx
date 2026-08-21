import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import Modal from './Modal'
import { propose } from './api'

/**
 * «Сказать тем, кто вправе править».
 *
 * Общий каталог и словарь закрыты намеренно, и до этой двери у учителя,
 * нашедшего опечатку в чужой задаче, не было **ничего**, кроме копии — то есть
 * дубля в общем каталоге. Здесь он говорит, а кому это идёт, решает сервер: по
 * владению того, о чём речь. Спрашивать адресата у человека незачем — он и не
 * должен знать, чья это задача.
 *
 * Видов четыре, и они не выдуманы: с чем приходят, то и перечислено. У
 * опечатки спрашивается **исправленный текст** — принятие вписывает его само,
 * и предложение, после которого администратору надо ещё раз сделать то же
 * самое руками, никто не станет ни писать, ни разбирать.
 */
export default function ProposeDialog({ problem, solution, onClose, onDone }) {
  const { t } = useTranslation()
  const [kind, setKind] = useState('typo')
  const [text, setText] = useState('')
  const [suggested, setSuggested] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      await propose({ kind, text, suggested, problem, solution })
      onDone()
    } catch (trouble) {
      setError(trouble.message)
      setBusy(false)
    }
  }

  return (
    <Modal title={t('propose.title')} onClose={onClose}>
      {error && <p className="error">{error}</p>}

      <label className="field">
        <span>{t('propose.kind')}</span>
        <select value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="typo">{t('propose.kinds.typo')}</option>
          <option value="tag">{t('propose.kinds.tag')}</option>
          <option value="solution">{t('propose.kinds.solution')}</option>
          <option value="other">{t('propose.kinds.other')}</option>
        </select>
      </label>

      <label className="field">
        <span>{t('propose.text')}</span>
        <textarea
          autoFocus
          rows="3"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>

      {kind !== 'other' && (
        <label className="field">
          <span>{t(`propose.suggested.${kind}`)}</span>
          <textarea
            rows="4"
            value={suggested}
            onChange={(event) => setSuggested(event.target.value)}
          />
        </label>
      )}

      <p className="hint">{t('propose.whereItGoes')}</p>

      <div className="row">
        <button type="button" onClick={send} disabled={busy || !text.trim()}>
          {t('propose.send')}
        </button>
        <button type="button" className="link" onClick={onClose}>
          {t('common.cancel')}
        </button>
      </div>
    </Modal>
  )
}
