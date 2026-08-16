import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ClassPicker from './ClassPicker'
import Modal from './Modal'
import { dateRange } from './dates'
import { planClear } from './scheduleLogic'

/** Bulk removal of the lessons inside the selected period. */
export default function ClearDialog({ range, slots, classes, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
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
    <Modal onClose={onClose} title={t('clear.title')}>
      <form onSubmit={handleSubmit}>
        <p className="hint">{dateRange(range.start, range.end)}</p>

        <ClassPicker classes={classes} picked={picked} onChange={setPicked} />

        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyRegular}
            onChange={(event) => setOnlyRegular(event.target.checked)}
          />
          {t('clear.keepSpecial')}
        </label>

        <p className="hint">{t('clear.willDelete', { count })}</p>

        <div className="actions">
          <button type="submit" disabled={busy || !count}>
            {t('common.delete')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
