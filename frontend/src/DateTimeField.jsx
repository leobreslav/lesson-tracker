import { useTranslation } from 'react-i18next'
import TimeField from './TimeField'
import { joinLocal, splitLocal } from './time24'

/**
 * Дата и время одним полем, время — в 24-часовой записи.
 *
 * Браузерным `datetime-local` это и было, и формат у него выбирает браузер —
 * по своему языку и языку системы, а не приложения: при английском (США)
 * время рисуется с AM/PM, и переключить это нечем. Поэтому поле разобрано
 * надвое: дату по-прежнему выбирает браузер (календарь у него хороший, а
 * двенадцатичасовой беды у даты нет), время набирают текстом (`TimeField`).
 *
 * Значение той же формы, что у `datetime-local` — «2026-09-27T14:30», — так
 * что перевод в ISO и обратно (`dates.toLocalInput`) остался прежним.
 */
export default function DateTimeField({ value, onChange, disabled = false, label }) {
  const { t } = useTranslation()
  const { date, time } = splitLocal(value)

  return (
    <span className="date-time">
      <input
        type="date"
        value={date}
        disabled={disabled}
        aria-label={t('time.date', { label })}
        onChange={(event) => onChange(joinLocal(event.target.value, time))}
      />
      <TimeField
        value={time}
        disabled={disabled}
        aria-label={t('time.time', { label })}
        onChange={(found) => onChange(joinLocal(date, found))}
      />
    </span>
  )
}
