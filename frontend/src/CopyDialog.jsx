import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ClassPicker from './ClassPicker'
import Modal from './Modal'
import { addDays, daysBetween } from './calendarLogic'
import { dateRange } from './dates'
import { planCopy } from './scheduleLogic'

/**
 * Copying the layout of the selected period onto another period.
 *
 * `onTargetChange` fires on every change of the target dates — the page can
 * load what already sits there, which makes the preview exact.
 */
export default function CopyDialog({
  source,
  slots,
  studyDates,
  classes,
  busy,
  title,
  note,
  onTargetChange,
  onSubmit,
  onClose,
}) {
  const { t } = useTranslation()
  const span = daysBetween(source.start, source.end) + 1
  const [target, setTarget] = useState({
    start: addDays(source.end, 1),
    end: addDays(source.end, span),
  })
  const [mode, setMode] = useState('merge')
  const [step, setStep] = useState(1) // 1 — каждую неделю, 2 — через неделю
  const [picked, setPicked] = useState(() => new Set(classes.map((item) => item.id)))

  // the callback lives in a ref: an inline function from the parent must not
  // restart the effect on every render
  const notify = useRef(onTargetChange)
  useEffect(() => {
    notify.current = onTargetChange
  })
  useEffect(() => {
    notify.current?.(target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.start, target.end])

  const valid = target.start && target.end && target.start <= target.end && picked.size
  const preview = valid
    ? planCopy({
        slots,
        studyDates,
        sourceStart: source.start,
        sourceEnd: source.end,
        targetStart: target.start,
        targetEnd: target.end,
        mode,
        step,
        classIds: picked,
      })
    : null

  const handleSubmit = (event) => {
    event.preventDefault()
    if (valid) {
      onSubmit({
        target_start: target.start,
        target_end: target.end,
        mode,
        step,
        classIds: [...picked],
      })
    }
  }

  return (
    <Modal onClose={onClose} title={title ?? t('copy.title')}>
      <form onSubmit={handleSubmit}>
        <p className="hint">
          {t('copy.source', {
            range: dateRange(source.start, source.end),
            days: t('common.dayCount', { count: span }),
          })}
        </p>

        <div className="row">
          <label>
            {t('common.from')}
            <input
              type="date"
              value={target.start}
              onChange={(event) => setTarget({ ...target, start: event.target.value })}
            />
          </label>
          <label>
            {t('common.to')}
            <input
              type="date"
              value={target.end}
              onChange={(event) => setTarget({ ...target, end: event.target.value })}
            />
          </label>
        </div>

        {/* Курс, который идёт раз в две недели, копировался вдвое чаще,
            чем бывает: цикл источника повторялся каждую неделю. Шаг
            растягивает цикл, а не источник — пропущенная неделя выходит
            сама, и предпросмотр считает её так же, как сервер. */}
        <div className="row">
          <label className="checkbox">
            <input
              type="radio"
              name="step"
              checked={step === 1}
              onChange={() => setStep(1)}
            />
            {t('copy.everyWeek')}
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="step"
              checked={step === 2}
              onChange={() => setStep(2)}
            />
            {t('copy.everyOtherWeek')}
          </label>
        </div>

        <div className="row">
          <label className="checkbox">
            <input
              type="radio"
              name="mode"
              checked={mode === 'merge'}
              onChange={() => setMode('merge')}
            />
            {t('copy.modeMerge')}
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="mode"
              checked={mode === 'replace'}
              onChange={() => setMode('replace')}
            />
            {t('copy.modeReplace')}
          </label>
        </div>

        <ClassPicker classes={classes} picked={picked} onChange={setPicked} />

        <p className="hint copy-preview">
          {preview
            ? t('copy.preview', {
                created: preview.created,
                skipped: preview.skipped,
              })
            : t('copy.checkPeriod')}
        </p>

        {note && <p className="hint">{note}</p>}

        <div className="actions">
          <button type="submit" disabled={busy || !valid}>
            {t('copy.submit')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
