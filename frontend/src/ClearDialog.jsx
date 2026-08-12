import { useState } from 'react'
import ClassPicker from './ClassPicker'
import Modal from './Modal'
import { formatRange } from './calendarLogic'
import { planClear } from './scheduleLogic'

/** Массовое удаление уроков за выделенный период. */
export default function ClearDialog({ range, slots, classes, busy, onSubmit, onClose }) {
  const [onlyRegular, setOnlyRegular] = useState(true)
  const [picked, setPicked] = useState(() => new Set(classes.map((item) => item.id)))

  const count = planClear({
    slots,
    start: range.start,
    end: range.end,
    onlyRegular,
    classIds: picked,
  })

  const handleSubmit = (event) => {
    event.preventDefault()
    onSubmit({ only_regular: onlyRegular, classIds: [...picked] })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3>Очистить период</h3>
        <p className="hint">{formatRange(range.start, range.end)}</p>

        <ClassPicker classes={classes} picked={picked} onChange={setPicked} />

        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyRegular}
            onChange={(event) => setOnlyRegular(event.target.checked)}
          />
          не трогать дополнительные и отменённые
        </label>

        <p className="hint">Будет удалено уроков: {count}.</p>

        <div className="actions">
          <button type="submit" disabled={busy || !count}>
            Удалить
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
