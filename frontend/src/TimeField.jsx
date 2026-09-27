import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { parseTime } from './time24'

/**
 * Время суток в 24-часовой записи, текстом.
 *
 * Браузерное `type="time"` формат выбирает само — по языку браузера и
 * системы: при английском (США) это AM/PM, и переключить его нечем. Поэтому
 * время набирают, а разбирает набранное `time24.parseTime`.
 *
 * **Набранное живёт своей строкой, пока не стало временем.** Иначе поле
 * мешало бы печатать: «14:3» временем не является, и, подставляй мы на
 * каждое нажатие разобранное значение, третья цифра стирала бы вторую.
 * Наверх уходит только то, что разобралось; уходя из поля, человек видит
 * либо приведённую запись, либо прежнее время — и пометку, пока набранное
 * ни во что не сложилось.
 *
 * `allowEmpty` — для мест, где «времени нет» законно: строку звонков
 * стирают, и ряд расписания снова показывает один номер. Там пустое поле
 * уходит наверх пустой строкой. Без флага пустое ничего не меняет: у окна
 * работы момент без времени не бывает.
 *
 * Значение принимается и с секундами («08:20:00» — так время отдаёт
 * сервер), показываются и возвращаются часы с минутами.
 */
export default function TimeField({
  value,
  onChange,
  disabled = false,
  allowEmpty = false,
  ...rest
}) {
  const { t } = useTranslation()
  const time = String(value ?? '').slice(0, 5)
  const [typed, setTyped] = useState(time)

  // время могло смениться снаружи: форму перечитали или строку убрали
  useEffect(() => {
    setTyped(time)
  }, [time])

  const empty = typed.trim() === ''
  const understood = parseTime(typed)
  const wrong = !empty && understood === null

  return (
    <input
      type="text"
      className="time-24"
      inputMode="numeric"
      autoComplete="off"
      maxLength={5}
      placeholder={t('time.placeholder')}
      value={typed}
      disabled={disabled}
      aria-invalid={wrong}
      title={wrong ? t('time.wrong') : undefined}
      onChange={(event) => {
        const said = event.target.value
        setTyped(said)

        const found = parseTime(said)
        if (found !== null) onChange(found)
        else if (allowEmpty && said.trim() === '') onChange('')
      }}
      onBlur={() => setTyped(empty && allowEmpty ? '' : (understood ?? time))}
      {...rest}
    />
  )
}
