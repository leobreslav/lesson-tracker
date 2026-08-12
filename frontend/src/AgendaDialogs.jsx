import { useState } from 'react'
import Modal from './Modal'
import { parseDate } from './calendarLogic'

function formatDay(iso) {
  return parseDate(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    weekday: 'long',
  })
}

/** Новый урок в свободном окне. */
export function AddLessonDialog({ date, number, classes, busy, onSubmit, onClose }) {
  const [classId, setClassId] = useState(classes[0]?.id ?? null)
  const [isExtra, setIsExtra] = useState(false)
  const [reason, setReason] = useState('')

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!classId) return

    onSubmit({
      school_class: classId,
      is_extra: isExtra,
      reason: isExtra ? reason.trim() : '',
    })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3>
          {formatDay(date)}, {number}-й урок
        </h3>

        {!classes.length ? (
          <p className="hint">
            Некому поставить этот урок: у всех подходящих классов номер уже
            занят, дата вне границ учебного года или классы ещё не заведены.
          </p>
        ) : (
          <>
            <label>
              Класс
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
              дополнительный урок
            </label>

            {isExtra && (
              <input
                value={reason}
                maxLength={200}
                placeholder="Пояснение: замена, кружок…"
                aria-label="Пояснение"
                disabled={busy}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !classes.length}>
            Добавить
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Что можно сделать с уже стоящим уроком. */
export function LessonMenu({ lesson, date, busy, onCancel, onRestore, onDelete, onClose }) {
  const [reason, setReason] = useState('')
  const [cancelling, setCancelling] = useState(false)

  const handleCancel = (event) => {
    event.preventDefault()
    onCancel(reason.trim())
  }

  return (
    <Modal onClose={onClose}>
      <h3>
        {lesson.class_name}, {lesson.lesson_number}-й урок
      </h3>
      <p className="hint">{formatDay(date)}</p>

      {lesson.is_extra && <p className="hint">Дополнительный урок.</p>}
      {lesson.is_cancelled && (
        <p className="hint">
          Отменён{lesson.reason ? `: ${lesson.reason}` : ''}.
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
            placeholder="Причина отмены"
            aria-label="Причина отмены"
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={busy}>
              Отменить урок
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setCancelling(false)}
            >
              Не надо
            </button>
          </div>
        </form>
      ) : (
        <div className="actions">
          {lesson.is_cancelled ? (
            <button type="button" disabled={busy} onClick={onRestore}>
              Вернуть
            </button>
          ) : (
            <button type="button" disabled={busy} onClick={() => setCancelling(true)}>
              Отменить
            </button>
          )}
          <button type="button" className="secondary" disabled={busy} onClick={onDelete}>
            Удалить
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Закрыть
          </button>
        </div>
      )}
    </Modal>
  )
}
