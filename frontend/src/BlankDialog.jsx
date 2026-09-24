import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { downloadBlank } from './api'

const CELLS = 15
const MAX_LABEL = 16

/**
 * Окно бланка с подписями: пятнадцать клеток, в каждую — имя задачи.
 *
 * Входов у него два, и окно одно. Со страницы работы клетки уже заполнены
 * именами её задач (`initial`), и остаётся поправить или сразу скачать. Из
 * списка работ клетки пустые: бланк подписывают под контрольную, которую в
 * системе ещё не завели, и заводить её ради печати незачем.
 *
 * **Подписи здесь — только для печати.** В задачи они не записываются:
 * исправить имя вопроса в работе — это правка работы, и делается она там же,
 * где остальные правки, а не окном «скачать бланк».
 *
 * Пустая клетка остаётся пустой полосой, как на обычном бланке: подпись
 * вписывают рукой.
 */
export default function BlankDialog({ initial = [], extra = 0, fileName, onClose }) {
  const { t } = useTranslation()
  const [labels, setLabels] = useState(() =>
    Array.from({ length: CELLS }, (_, index) => (initial[index] ?? '').slice(0, MAX_LABEL)),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const change = (index, value) => {
    setLabels((current) => current.map((label, at) => (at === index ? value : label)))
    setError(null)
  }

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await downloadBlank(labels, fileName)
    } catch (failure) {
      setError(failure)
    } finally {
      setBusy(false)
    }
  }

  const invalid = error?.code === 'blank_label_too_long' ? error.params?.cell : null

  return (
    <Modal onClose={onClose} title={t('blank.title')}>
      <form onSubmit={submit}>
        <p className="hint">{t('blank.hint')}</p>

        {/* Клетки идут в том же порядке, что на листе, и подписаны тем же
            номером, что стоит в углу клетки на бумаге */}
        <div className="blank-labels">
          {labels.map((label, index) => (
            <label key={index} className="blank-label">
              <span>{index + 1}</span>
              <input
                value={label}
                maxLength={MAX_LABEL}
                disabled={busy}
                aria-invalid={invalid === index + 1 ? 'true' : undefined}
                onChange={(event) => change(index, event.target.value)}
              />
            </label>
          ))}
        </div>

        {/* Задач больше, чем клеток, — сказать сразу, а не оставить человека
            гадать, куда делась шестнадцатая */}
        {extra > 0 && <p className="hint warning">{t('blank.extra', { count: extra })}</p>}

        {error && (
          <p className="error" role="alert">
            {error.message}
          </p>
        )}

        <div className="actions">
          <button type="submit" disabled={busy}>
            {t('blank.download')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
