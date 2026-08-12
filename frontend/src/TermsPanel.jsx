import { useState } from 'react'
import { formatRange } from './calendarLogic'
import { termColorIndex } from './termColors'

const EMPTY_FORM = { name: '', start_date: '', end_date: '' }

/**
 * Термы года: список, добавление и правка.
 *
 * Термы не обязаны покрывать год целиком — дни между ними просто не входят
 * ни в один терм, и это нормальное состояние, а не ошибка.
 */
export default function TermsPanel({ terms, year, studyDays, busy, onCreate, onUpdate, onDelete }) {
  const [form, setForm] = useState(null) // {id?, name, start_date, end_date}

  const open = (term) =>
    setForm(
      term
        ? {
            id: term.id,
            name: term.name,
            start_date: term.start_date,
            end_date: term.end_date,
          }
        : { ...EMPTY_FORM, start_date: year.start_date, end_date: year.start_date },
    )

  const submit = (event) => {
    event.preventDefault()
    const { id, ...fields } = form
    if (!fields.name.trim()) return

    const payload = { ...fields, name: fields.name.trim() }
    setForm(null)
    if (id) onUpdate(id, payload)
    else onCreate(payload)
  }

  return (
    <section className="panel">
      <h3>Термы</h3>

      {!terms.length && (
        <p className="hint">
          Четвертей пока нет. Без них раскладка считается по всему году сразу.
        </p>
      )}

      <ul className="terms">
        {terms.map((term) => (
          <li key={term.id} className={`term-${termColorIndex(terms, term.id)}`}>
            <div>
              <strong>{term.name}</strong>
              <span className="hint">
                {formatRange(term.start_date, term.end_date)} ·{' '}
                {studyDays[term.id] ?? 0} учебных дней
              </span>
            </div>
            <button
              type="button"
              className="link"
              title="Изменить"
              disabled={busy}
              onClick={() => open(term)}
            >
              ✎
            </button>
            <button
              type="button"
              className="link"
              aria-label={`Удалить терм ${term.name}`}
              disabled={busy}
              onClick={() => onDelete(term)}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>

      {form ? (
        <form className="term-form" onSubmit={submit}>
          <input
            autoFocus
            value={form.name}
            maxLength={100}
            placeholder="Например, 1 четверть"
            aria-label="Название терма"
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <div className="row">
            <label>
              с
              <input
                type="date"
                value={form.start_date}
                min={year.start_date}
                max={year.end_date}
                onChange={(event) =>
                  setForm({ ...form, start_date: event.target.value })
                }
              />
            </label>
            <label>
              по
              <input
                type="date"
                value={form.end_date}
                min={year.start_date}
                max={year.end_date}
                onChange={(event) => setForm({ ...form, end_date: event.target.value })}
              />
            </label>
          </div>
          <div className="actions">
            <button type="submit" disabled={busy || !form.name.trim()}>
              {form.id ? 'Сохранить' : 'Добавить'}
            </button>
            <button type="button" className="secondary" onClick={() => setForm(null)}>
              Отмена
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="secondary" disabled={busy} onClick={() => open(null)}>
          + терм
        </button>
      )}
    </section>
  )
}
