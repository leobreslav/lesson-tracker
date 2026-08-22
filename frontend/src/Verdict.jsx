import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { setMark } from './api'

/**
 * Балл за **этот** ответ, и снятие повторным нажатием.
 *
 * Ось одна — «что он решил», — и вопрос из одного балла это её частный
 * случай: ✓ значит единицу, ✗ значит ноль. Поэтому у обычной задачи ничего
 * не изменилось: те же две кнопки и то же движение. А там, где вопрос стоит
 * трёх баллов, стало возможным то, чего раньше не было вовсе, — поставить
 * два: галочка выражала только края шкалы.
 *
 * Третьей кнопки «снять» нет: нажать ту же второй раз — движение, которое
 * человек делает не читая. А снятие нужно — учитель передумал или увидел,
 * что смотрел не ту отправку.
 *
 * Балл приклеен к этой строке журнала. Пришла новая отправка — балл
 * **остаётся** за прошлой, а в таблице у клетки появляется точка «надо
 * посмотреть». Гасить оценку за то, что ученик прислал ещё раз, значило бы
 * стирать работу учителя чужими руками.
 */
export default function Verdict({ submission, maximum = 1, onChanged, onError }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)

  const put = async (value) => {
    setBusy(true)
    try {
      await setMark(submission.id, submission.mark === value ? null : value)
      await onChanged()
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const chip = (value, label, extra = '', title = null) => (
    <button
      key={value}
      type="button"
      className={submission.mark === value ? `chip active ${extra}` : 'chip'}
      disabled={busy}
      aria-pressed={submission.mark === value}
      title={title ?? t('table.markPoints', { value, maximum })}
      onClick={() => put(value)}
    >
      {label}
    </button>
  )

  // вопрос из одного балла — те же ✓ и ✗, к которым учитель привык
  if (maximum === 1) {
    return (
      <span className="verdict-buttons">
        {chip(1, '✓', '', t('table.markCorrect'))}
        {chip(0, '✗', 'wrong', t('table.markWrong'))}
      </span>
    )
  }

  // до шести значений помещаются кнопками: нажатие дешевле ввода числа
  if (maximum <= 5) {
    return (
      <span className="verdict-buttons">
        {Array.from({ length: maximum + 1 }, (_, value) =>
          chip(value, String(value), value === 0 ? 'wrong' : ''),
        )}
      </span>
    )
  }

  return (
    <span className="verdict-buttons">
      <input
        type="number"
        className="mark-input"
        min="0"
        max={maximum}
        value={submission.mark ?? ''}
        disabled={busy}
        aria-label={t('table.markPoints', { value: '', maximum })}
        onChange={(event) => {
          const raw = event.target.value
          if (raw === '') return put(null)
          const value = Math.min(maximum, Math.max(0, Number(raw)))
          return put(value)
        }}
      />
      <span className="hint">/ {maximum}</span>
    </span>
  )
}
