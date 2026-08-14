import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { setVerdict } from './api'

/**
 * Две кнопки отметки — «верно» и «неверно» — и снятие повторным нажатием.
 *
 * Третьей кнопки «снять» нет: нажать ту же второй раз — движение, которое
 * человек делает сам, не читая подписи. А снятие нужно: учитель передумал
 * или увидел, что смотрел не ту отправку.
 *
 * Отметка приклеена к **этой** строке журнала. Пришла новая отправка — она
 * не проверена, и это не сбой, а то, как устроен ответ на переделку.
 */
export default function Verdict({ submission, onChanged, onError }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)

  const mark = async (value) => {
    setBusy(true)
    try {
      await setVerdict(submission.id, submission.is_correct === value ? null : value)
      await onChanged()
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="verdict-buttons">
      <button
        type="button"
        className={submission.is_correct === true ? 'chip active' : 'chip'}
        disabled={busy}
        aria-pressed={submission.is_correct === true}
        title={t('table.markCorrect')}
        onClick={() => mark(true)}
      >
        ✓
      </button>
      <button
        type="button"
        className={submission.is_correct === false ? 'chip active wrong' : 'chip'}
        disabled={busy}
        aria-pressed={submission.is_correct === false}
        title={t('table.markWrong')}
        onClick={() => mark(false)}
      >
        ✗
      </button>
    </span>
  )
}
