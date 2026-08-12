import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { eachDate } from './calendarLogic'
import { dateRange } from './dates'

/** Asking for the name of a break over the selected range. */
export default function RangeDialog({ range, busy, onSubmit, onCancel }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState('')

  const handleSubmit = (event) => {
    event.preventDefault()
    onSubmit(title.trim())
  }

  const length = eachDate(range.start_date, range.end_date).length

  return (
    <Modal onClose={onCancel}>
      <form onSubmit={handleSubmit}>
        <h3>{t('rangeDialog.title')}</h3>
        <p className="hint">
          {dateRange(range.start_date, range.end_date)} —{' '}
          {t('common.dayCount', { count: length })}
        </p>

        <input
          autoFocus
          value={title}
          maxLength={120}
          placeholder={t('rangeDialog.placeholder')}
          onChange={(event) => setTitle(event.target.value)}
        />

        <div className="actions">
          <button type="submit" disabled={busy}>
            {t('common.add')}
          </button>
          <button type="button" className="secondary" onClick={onCancel}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
