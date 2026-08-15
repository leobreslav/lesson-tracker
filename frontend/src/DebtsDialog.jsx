import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { closeSlots, fetchUnclosed } from './api'
import { shortDate, shortWeekday } from './dates'

/**
 * Закрыть прошедшие занятия, за которыми ничего не записано.
 *
 * Пачкой — потому что вернувшийся из отпуска обязан иметь возможность
 * закрыть пять дней разом: заставлять открывать каждый день по одному
 * значит не получить отметок вовсе.
 *
 * Но **с просмотром**, и разница именно здесь: у каждой строки подставлена
 * тема из раскладки, и она на экране. «Подтвердить пять предложений» — не
 * то же, что «отметить всё не глядя»; второе превращает запись в
 * формальность, а формально заполненное поле хуже вычисленного — оно
 * выглядит фактом.
 *
 * Ответов у строки два: «было» (записываем подсказанную тему) и «не было»
 * (отмена с причиной). Неотвеченная строка не отправляется вовсе: молчание
 * — это честно «пока не знаю», и выдумывать за человека нечего.
 */
export default function DebtsDialog({ courseId = null, busy, onDone, onClose }) {
  const { t } = useTranslation()
  const [slots, setSlots] = useState(null)
  const [choice, setChoice] = useState({}) // id → {kind, reason}
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchUnclosed()
      .then((answer) => setSlots(answer.slots))
      .catch((err) => setError(err.message))
  }, [])

  const shown = (slots ?? []).filter(
    (slot) => courseId === null || slot.course.id === courseId,
  )

  const pick = (id, kind) =>
    setChoice((current) => ({
      ...current,
      [id]: current[id]?.kind === kind ? undefined : { kind, reason: '' },
    }))

  const reasonOf = (id, reason) =>
    setChoice((current) => ({ ...current, [id]: { ...current[id], reason } }))

  const closed = shown
    .filter((slot) => choice[slot.id])
    .map((slot) =>
      choice[slot.id].kind === 'held'
        ? { slot: slot.id, lesson: slot.topic.id }
        : { slot: slot.id, cancelled: true, reason: choice[slot.id].reason },
    )

  const submit = (event) => {
    event.preventDefault()
    if (!closed.length) return

    closeSlots(closed)
      .then(onDone)
      .catch((err) => setError(err.message))
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{t('debts.title')}</h3>
        <p className="hint">{t('debts.hint')}</p>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {slots === null ? (
          <p>{t('common.loading')}</p>
        ) : shown.length === 0 ? (
          <p className="hint">{t('debts.none')}</p>
        ) : (
          <ul className="debt-list">
            {shown.map((slot) => (
              <li key={slot.id} data-debt={slot.id}>
                <span className="debt-day">
                  {shortWeekday(slot.date)} {shortDate(slot.date)} ·{' '}
                  {t('today.lessonNumber', { number: slot.lesson_number })}
                </span>
                <span className="debt-course">{slot.course.name}</span>
                <span className="debt-topic">
                  {slot.topic ? slot.topic.title : <i>{t('debts.noTopic')}</i>}
                </span>
                <span className="debt-choice">
                  {/* без темы записывать нечего: раскладке нечего предложить */}
                  {slot.topic && (
                    <button
                      type="button"
                      className={
                        choice[slot.id]?.kind === 'held' ? 'chip active' : 'chip'
                      }
                      onClick={() => pick(slot.id, 'held')}
                    >
                      {t('debts.held')}
                    </button>
                  )}
                  <button
                    type="button"
                    className={
                      choice[slot.id]?.kind === 'skipped' ? 'chip active' : 'chip'
                    }
                    onClick={() => pick(slot.id, 'skipped')}
                  >
                    {t('debts.skipped')}
                  </button>
                </span>
                {choice[slot.id]?.kind === 'skipped' && (
                  <input
                    value={choice[slot.id].reason}
                    maxLength={200}
                    placeholder={t('agenda.menu.cancelReason')}
                    aria-label={t('agenda.menu.cancelReason')}
                    onChange={(event) => reasonOf(slot.id, event.target.value)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !closed.length}>
            {t('debts.submit', { count: closed.length })}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
