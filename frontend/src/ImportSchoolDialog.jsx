import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { fetchImportPreview } from './api'

/**
 * Copying the school timetable into one's own schedule.
 *
 * The dialog exists to make one thing unmistakable: this happens once. The
 * copies become ordinary lessons and stop tracking the timetable, so the
 * wording says so before the button rather than after.
 *
 * The preview comes from the server, not from arithmetic here — the same
 * planning code the import will run, so the numbers cannot disagree.
 */
export default function ImportSchoolDialog({ year, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState({ start: year.start_date, end: year.end_date })
  const [preview, setPreview] = useState(null)
  const [picked, setPicked] = useState(null) // null = every course of mine
  const [mode, setMode] = useState('merge')
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setPreview(null)

    fetchImportPreview({ year: year.id, ...period })
      .then((data) => {
        if (cancelled) return
        setPreview(data)
        setPicked((current) =>
          current ?? new Set(data.courses.map((course) => course.id)),
        )
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [year.id, period.start, period.end])

  const courses = preview?.courses ?? []
  const chosen = courses.filter((course) => picked?.has(course.id))
  const total = chosen.reduce((sum, course) => sum + course.created, 0)
  const available = chosen.reduce((sum, course) => sum + course.available, 0)

  const toggle = (id) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setPicked(next)
  }

  const submit = (event) => {
    event.preventDefault()
    if (!chosen.length) return

    onSubmit({
      year: year.id,
      // every course of mine is sent as null: fewer ids to go stale
      courses: chosen.length === courses.length ? null : chosen.map((c) => c.id),
      start: period.start,
      end: period.end,
      mode,
    })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h3>{t('import.title')}</h3>
        <p className="hint">{t('import.once')}</p>

        <div className="row">
          <label>
            {t('common.from')}
            <input
              type="date"
              value={period.start}
              min={year.start_date}
              max={year.end_date}
              onChange={(event) =>
                setPeriod({ ...period, start: event.target.value })
              }
            />
          </label>
          <label>
            {t('common.to')}
            <input
              type="date"
              value={period.end}
              min={year.start_date}
              max={year.end_date}
              onChange={(event) => setPeriod({ ...period, end: event.target.value })}
            />
          </label>
        </div>

        {error && <p className="error">{error}</p>}

        {preview === null && !error && <p>{t('common.loading')}</p>}

        {preview !== null && !courses.length && (
          <p className="hint">{t('import.nothing')}</p>
        )}

        {courses.length > 0 && (
          <>
            <div className="class-picker">
              <span className="hint">{t('classPicker.label')}</span>
              {courses.map((course) => (
                <label key={course.id} className="checkbox">
                  <input
                    type="checkbox"
                    checked={picked?.has(course.id) ?? false}
                    onChange={() => toggle(course.id)}
                  />
                  {course.name}
                  <span className="hint">
                    {t('common.lessonCount', { count: course.available })}
                  </span>
                </label>
              ))}
            </div>

            <p className="hint">
              {t('import.preview', {
                lessons: t('common.lessonCount', { count: total }),
                courses: t('common.classCount', { count: chosen.length }),
              })}
            </p>

            {available > total && (
              <p className="hint">
                {t('import.skipped', { count: available - total })}
              </p>
            )}

            {preview.conflicts.length > 0 && (
              <>
                <p className="error">
                  {t('import.conflicts', { count: preview.conflicts.length })}
                </p>
                <ul className="csv-warnings">
                  {preview.conflicts.slice(0, 5).map((conflict) => (
                    <li
                      key={`${conflict.date}-${conflict.lesson_number}`}
                      className="hint"
                    >
                      {conflict.message}
                    </li>
                  ))}
                </ul>
              </>
            )}

            <div className="row">
              <label className="checkbox">
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === 'merge'}
                  onChange={() => setMode('merge')}
                />
                {t('import.modeMerge')}
              </label>
              <label className="checkbox">
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === 'replace'}
                  onChange={() => setMode('replace')}
                />
                {t('import.modeReplace')}
              </label>
            </div>

            {mode === 'replace' && <p className="error">{t('import.replaceWarning')}</p>}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !chosen.length}>
            {t('import.submit')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
