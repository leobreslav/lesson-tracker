import { useState } from 'react'
import Modal from './Modal'
import { eachDate, formatRange } from './calendarLogic'

function pluralDays(count) {
  const tail = count % 10
  const hundred = count % 100

  if (tail === 1 && hundred !== 11) return 'день'
  if (tail >= 2 && tail <= 4 && (hundred < 10 || hundred >= 20)) return 'дня'
  return 'дней'
}

/** Ввод названия каникул для выделенного диапазона. */
export default function RangeDialog({ range, busy, onSubmit, onCancel }) {
  const [title, setTitle] = useState('')

  const handleSubmit = (event) => {
    event.preventDefault()
    onSubmit(title.trim())
  }

  const length = eachDate(range.start_date, range.end_date).length

  return (
    <Modal onClose={onCancel}>
      <form onSubmit={handleSubmit}>
        <h3>Новые каникулы</h3>
        <p className="hint">
          {formatRange(range.start_date, range.end_date)} — {length}{' '}
          {pluralDays(length)}
        </p>

        <input
          autoFocus
          value={title}
          maxLength={120}
          placeholder="Название, например «Осенние каникулы»"
          onChange={(event) => setTitle(event.target.value)}
        />

        <div className="actions">
          <button type="submit" disabled={busy}>
            Добавить
          </button>
          <button type="button" className="secondary" onClick={onCancel}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
