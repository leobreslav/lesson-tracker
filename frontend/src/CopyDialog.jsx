import { useEffect, useRef, useState } from 'react'
import ClassPicker from './ClassPicker'
import Modal from './Modal'
import { addDays, daysBetween, formatRange } from './calendarLogic'
import { planCopy } from './scheduleLogic'

/**
 * Копирование раскладки выделенного периода на другой период.
 *
 * `onTargetChange` зовётся при каждой смене целевых дат — страница может
 * подгрузить, что там уже стоит, и предпросмотр станет точным.
 */
export default function CopyDialog({
  source,
  slots,
  studyDates,
  classes,
  busy,
  title = 'Скопировать расписание',
  note,
  onTargetChange,
  onSubmit,
  onClose,
}) {
  const span = daysBetween(source.start, source.end) + 1
  const [target, setTarget] = useState({
    start: addDays(source.end, 1),
    end: addDays(source.end, span),
  })
  const [mode, setMode] = useState('merge')
  const [picked, setPicked] = useState(() => new Set(classes.map((item) => item.id)))

  // колбэк держим в ref: инлайновая функция родителя не должна
  // перезапускать эффект на каждой перерисовке
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
        classIds: [...picked],
      })
    }
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3>{title}</h3>
        <p className="hint">
          Источник: {formatRange(source.start, source.end)} — {span} дн.
          Дни недели совпадут: понедельники поедут на понедельники.
        </p>

        <div className="row">
          <label>
            С
            <input
              type="date"
              value={target.start}
              onChange={(event) => setTarget({ ...target, start: event.target.value })}
            />
          </label>
          <label>
            по
            <input
              type="date"
              value={target.end}
              onChange={(event) => setTarget({ ...target, end: event.target.value })}
            />
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
            добавить к существующим
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="mode"
              checked={mode === 'replace'}
              onChange={() => setMode('replace')}
            />
            заменить обычные уроки
          </label>
        </div>

        <ClassPicker classes={classes} picked={picked} onChange={setPicked} />

        <p className="hint">
          {preview
            ? `Будет создано примерно ${preview.created} уроков, пропущено ` +
              `${preview.skipped} (неучебные дни и занятые номера).`
            : 'Проверьте период и выбор классов.'}
        </p>

        {note && <p className="hint">{note}</p>}

        <div className="actions">
          <button type="submit" disabled={busy || !valid}>
            Скопировать
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
