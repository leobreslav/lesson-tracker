import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { dateRange } from './dates'
import { termColorIndex } from './termColors'

const EMPTY_FORM = { name: '', start_date: '', end_date: '' }

/**
 * The terms of a year: the list, adding and editing.
 *
 * Terms need not cover the year completely — the days between them belong to
 * no term, and that is a normal state rather than an error.
 */
export default function TermsPanel({ terms, year, studyDays, busy, onCreate, onUpdate, onDelete }) {
  const { t } = useTranslation()
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
      <h3>{t('calendar.terms.title')}</h3>

      {!terms.length && <p className="hint">{t('calendar.terms.empty')}</p>}

      <ul className="terms">
        {terms.map((term) => (
          <li key={term.id} className={`term-${termColorIndex(terms, term.id)}`}>
            <div>
              <strong>{term.name}</strong>
              <span className="hint">
                {dateRange(term.start_date, term.end_date)} ·{' '}
                {t('common.studyDayCount', { count: studyDays[term.id] ?? 0 })}
              </span>
            </div>
            <button
              type="button"
              className="link"
              title={t('common.edit')}
              disabled={busy}
              onClick={() => open(term)}
            >
              ✎
            </button>
            <button
              type="button"
              className="link"
              aria-label={t('calendar.terms.delete', { name: term.name })}
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
            placeholder={t('calendar.terms.placeholder')}
            aria-label={t('calendar.terms.nameLabel')}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <div className="row">
            <label>
              {t('common.from')}
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
              {t('common.to')}
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
              {form.id ? t('common.save') : t('common.add')}
            </button>
            <button type="button" className="secondary" onClick={() => setForm(null)}>
              {t('common.cancel')}
            </button>
          </div>
        </form>
      ) : (
        <button type="button" className="secondary" disabled={busy} onClick={() => open(null)}>
          {t('calendar.terms.add')}
        </button>
      )}
    </section>
  )
}
