import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { weekdayWithDate } from './dates'

/** A new lesson in a free window. */
export function AddLessonDialog({ date, number, classes, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [classId, setClassId] = useState(classes[0]?.id ?? null)
  const [isExtra, setIsExtra] = useState(false)
  const [reason, setReason] = useState('')

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!classId) return

    onSubmit({
      course: classId,
      is_extra: isExtra,
      reason: isExtra ? reason.trim() : '',
    })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3>{t('agenda.add.title', { date: weekdayWithDate(date), number })}</h3>

        {!classes.length ? (
          <p className="hint">{t('agenda.add.nobody')}</p>
        ) : (
          <>
            <label>
              {t('agenda.add.classLabel')}
              <select
                autoFocus
                value={classId ?? ''}
                disabled={busy}
                onChange={(event) => setClassId(Number(event.target.value))}
              >
                {classes.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={isExtra}
                disabled={busy}
                onChange={(event) => setIsExtra(event.target.checked)}
              />
              {t('agenda.add.extra')}
            </label>

            {isExtra && (
              <input
                value={reason}
                maxLength={200}
                placeholder={t('agenda.add.reasonPlaceholder')}
                aria-label={t('agenda.add.reasonLabel')}
                disabled={busy}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !classes.length}>
            {t('common.add')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** What can be done with a lesson that is already there. */
export function LessonMenu({ lesson, date, busy, onCancel, onRestore, onDelete, onClose }) {
  const { t } = useTranslation()
  const [reason, setReason] = useState('')
  const [cancelling, setCancelling] = useState(false)

  const handleCancel = (event) => {
    event.preventDefault()
    onCancel(reason.trim())
  }

  return (
    <Modal onClose={onClose}>
      <h3>
        {t('agenda.menu.title', {
          className: lesson.course_name,
          number: lesson.lesson_number,
        })}
      </h3>
      <p className="hint">{weekdayWithDate(date)}</p>

      {lesson.is_extra && <p className="hint">{t('agenda.menu.extra')}</p>}
      {lesson.is_cancelled && (
        <p className="hint">
          {t('agenda.menu.cancelled', {
            reason: lesson.reason ? `: ${lesson.reason}` : '',
          })}
        </p>
      )}
      {!lesson.is_cancelled && lesson.reason && (
        <p className="hint">{lesson.reason}</p>
      )}

      {cancelling ? (
        <form onSubmit={handleCancel}>
          <input
            autoFocus
            value={reason}
            maxLength={200}
            placeholder={t('agenda.menu.cancelReason')}
            aria-label={t('agenda.menu.cancelReason')}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy}>
              {t('agenda.menu.cancelSubmit')}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setCancelling(false)}
            >
              {t('agenda.menu.cancelAbort')}
            </button>
          </div>
        </form>
      ) : (
        <div className="actions">
          {lesson.is_cancelled ? (
            <button type="button" disabled={busy} onClick={onRestore}>
              {t('agenda.menu.restore')}
            </button>
          ) : (
            <button type="button" disabled={busy} onClick={() => setCancelling(true)}>
              {t('agenda.menu.cancel')}
            </button>
          )}
          <button type="button" className="secondary" disabled={busy} onClick={onDelete}>
            {t('common.delete')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('agenda.menu.close')}
          </button>
        </div>
      )}
    </Modal>
  )
}
