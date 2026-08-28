import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Hint from './Hint'
import { weekdayHeadings } from './dates'
import { updateSchoolYear } from './api'

/**
 * Какие дни недели в школе учебные.
 *
 * Поле это у года было с самого начала (`SchoolYear.weekend_days`), и
 * правилось только запросом к API: школа с учебной субботой — обычное дело, а
 * сказать об этом приложению было нечем. Отсюда панель, и стоит она рядом со
 * звонками: там же отвечают на второй вопрос про устройство недели — сколько
 * уроков в дне.
 *
 * **Галочки стоят на учебных днях, а не на выходных.** Хранится обратное, и
 * перевод живёт здесь, в одном месте: спрашивают «суббота у вас учебная?», и
 * форма должна отвечать на тот вопрос, который задают.
 *
 * **Год выбирается явно, если он не один.** Остальной экран берёт первый год
 * молча, и для списка классов это верно; здесь молчание стоило бы дороже —
 * переложенная неделя видна не в этой панели, а в расписании, и связать одно
 * с другим человек уже не сможет.
 *
 * Последняя галочка не снимается: год без единого учебного дня сервер не
 * примет (`year_weekend_full`), и предлагать выбор, ведущий в отказ, незачем.
 */
export default function StudyDaysPanel({ years, busy, onSaved }) {
  const { t } = useTranslation()
  const [yearId, setYearId] = useState(null)
  const [weekend, setWeekend] = useState([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  // Год берётся тот же, что и всем экраном, — первый в списке; выбранный
  // человеком переживает перезагрузку списка после сохранения
  const year = years.find((one) => one.id === yearId) ?? years[0] ?? null

  useEffect(() => {
    if (year === null) return
    setYearId(year.id)
    setWeekend(year.weekend_days)
  }, [year])

  if (year === null) {
    return (
      <section className="panel">
        <h3>{t('studyDays.title')}</h3>
        <p className="hint">{t('studyDays.noYear')}</p>
      </section>
    )
  }

  const isStudy = (weekday) => !weekend.includes(weekday)
  const studyCount = 7 - weekend.length

  const toggle = (weekday) => {
    setSaved(false)
    setWeekend((current) =>
      current.includes(weekday)
        ? current.filter((one) => one !== weekday)
        : [...current, weekday].sort((a, b) => a - b),
    )
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await updateSchoolYear(year.id, { weekend_days: weekend })
      setSaved(true)
      await onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const disabled = busy || saving

  return (
    <section className="panel">
      <h3>{t('studyDays.title')}</h3>
      <Hint short={t('studyDays.hint')} more={t('studyDays.hintMore')} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {years.length > 1 && (
        <div className="row middle">
          <label htmlFor="study-days-year">{t('studyDays.year')}</label>
          <select
            id="study-days-year"
            value={year.id}
            disabled={disabled}
            onChange={(event) => {
              const chosen = years.find(
                (one) => one.id === Number(event.target.value),
              )
              setSaved(false)
              setYearId(chosen.id)
              setWeekend(chosen.weekend_days)
            }}
          >
            {years.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="row middle">
        {weekdayHeadings().map(({ weekday, label }) => (
          <label key={weekday} className="checkbox">
            <input
              type="checkbox"
              checked={isStudy(weekday)}
              // последний учебный день не снимается: год без учебных дней
              // сервер не примет, а кнопка, умеющая только отказать, честнее
              // не нажиматься
              disabled={disabled || (isStudy(weekday) && studyCount === 1)}
              onChange={() => toggle(weekday)}
            />
            {label}
          </label>
        ))}
      </div>

      <div className="actions">
        <button type="button" disabled={disabled} onClick={save}>
          {t('common.save')}
        </button>
        {saved && <span className="hint">{t('studyDays.saved')}</span>}
      </div>
    </section>
  )
}
