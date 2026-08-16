import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
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

/**
 * What can be done with a lesson that is already there.
 *
 * Перенос стоит здесь же, рядом с отменой, и это не случайно: для человека
 * это одно действие, а в данных — отмена с причиной плюс дополнительное
 * занятие на новой дате. Двойную запись делает сервер; здесь только форма.
 *
 * **Первым стоит «Открыть урок»**, и это же единственная синяя кнопка. Меню
 * отвечало только на вопрос «что сделать с клеткой расписания» — отменить,
 * перенести, удалить, — и попасть из расписания в само занятие было нечем:
 * приходилось идти через «Сегодня» и долистывать до нужного дня. А работают
 * с занятием чаще, чем правят сетку.
 *
 * Синей до этого была «Отменить», по единственной причине — она стояла
 * первой. Отмена редка и разрушительна, и главной кнопкой быть не должна:
 * то же решение, что увело её в «⋯» на самой странице урока.
 */
export function LessonMenu({
  lesson,
  date,
  busy,
  onCancel,
  onRestore,
  onDelete,
  onMove,
  onClose,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState(null) // null | 'cancel' | 'move'
  const [target, setTarget] = useState({ date: '', number: lesson.lesson_number })

  const handleCancel = (event) => {
    event.preventDefault()
    onCancel(reason.trim())
  }

  const handleMove = (event) => {
    event.preventDefault()
    if (!target.date) return

    onMove({
      date: target.date,
      lesson_number: Number(target.number),
      // причина пишется на языке того, кто нажал: это контент в базе, и
      // сервер его не сочиняет
      reason: reason.trim() || t('agenda.menu.movedReason', { date: target.date }),
    })
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

      {mode === 'cancel' && (
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
            <button type="button" className="secondary" onClick={() => setMode(null)}>
              {t('agenda.menu.cancelAbort')}
            </button>
          </div>
        </form>
      )}

      {mode === 'move' && (
        <form onSubmit={handleMove}>
          <p className="hint">{t('agenda.menu.moveHint')}</p>
          <div className="row">
            <input
              autoFocus
              type="date"
              value={target.date}
              aria-label={t('agenda.menu.moveDate')}
              onChange={(event) =>
                setTarget((current) => ({ ...current, date: event.target.value }))
              }
            />
            <input
              type="number"
              min={1}
              max={10}
              value={target.number}
              aria-label={t('agenda.menu.moveNumber')}
              onChange={(event) =>
                setTarget((current) => ({ ...current, number: event.target.value }))
              }
            />
          </div>
          <input
            value={reason}
            maxLength={200}
            placeholder={t('agenda.menu.moveReason')}
            aria-label={t('agenda.menu.moveReason')}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy || !target.date}>
              {t('agenda.menu.moveSubmit')}
            </button>
            <button type="button" className="secondary" onClick={() => setMode(null)}>
              {t('agenda.menu.cancelAbort')}
            </button>
          </div>
        </form>
      )}

      {mode === null && (
        <div className="actions">
          <button type="button" onClick={() => navigate(`/lesson/${lesson.id}`)}>
            {t('today.openLesson')}
          </button>
          {lesson.is_cancelled ? (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={onRestore}
            >
              {t('agenda.menu.restore')}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setMode('cancel')}
              >
                {t('agenda.menu.cancel')}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setMode('move')}
              >
                {t('agenda.menu.move')}
              </button>
            </>
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
