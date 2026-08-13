import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { previewPlanCsv } from './api'
import { decodeCsv, parsePlanCsv } from './planCsv'

const PREVIEW_LIMIT = 20
const MODES = ['replace', 'append', 'sync']

/**
 * Importing a plan from CSV: the file, the mode and two previews.
 *
 * The file itself is parsed here, in the browser, so the person sees what was
 * recognised before anything is sent. What it will *cost* comes from the
 * server — only it knows which lessons have content and which files nothing
 * else points at. That answer is the reason this dialog exists in its present
 * form: replace deletes the lesson bodies and the attachments along with the
 * rows, and a file whose last reference goes is gone from the store for good.
 */
export default function ImportDialog({ classId, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [file, setFile] = useState(null)
  const [mode, setMode] = useState('replace')
  const [parsed, setParsed] = useState(null) // {rows, warnings, hasIds}
  const [cost, setCost] = useState(null) // the server's answer
  const [expanded, setExpanded] = useState(false)
  const [agreed, setAgreed] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)

  const take = async (chosen) => {
    setError(null)
    setFile(chosen)
    setParsed(null)
    setCost(null)
    setAgreed(false)
    if (!chosen) return

    try {
      const result = parsePlanCsv(decodeCsv(await chosen.arrayBuffer()))
      setParsed(result)
      // a file without ids cannot be synced; do not leave the radio on it
      if (!result.hasIds && mode === 'sync') setMode('replace')
    } catch {
      setError(t('csv.unreadable'))
    }
  }

  // the cost is asked again on every change of mode: replace and sync lose
  // entirely different things
  useEffect(() => {
    if (!file || !parsed) return undefined

    let current = true
    setCost(null)
    setAgreed(false)

    previewPlanCsv(classId, file, mode)
      .then((result) => current && setCost(result))
      .catch(() => current && setCost(null))

    return () => {
      current = false
    }
  }, [classId, file, parsed, mode])

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files?.[0] ?? null)
  }

  const preview = parsed?.rows.slice(0, PREVIEW_LIMIT) ?? []
  const losing = Boolean(cost && (cost.with_content || cost.with_attachments))
  const refused = Boolean(cost?.errors?.length)
  // an explicit tick, not just a click on a button: this is the one place
  // where work disappears without a copy anywhere
  const blocked =
    busy || !parsed?.rows.length || refused || (losing && !agreed)

  const handleSubmit = (event) => {
    event.preventDefault()
    if (file && !blocked) onSubmit({ file, mode })
  }

  return (
    <Modal onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3>{t('csv.title')}</h3>
        <p className="hint">{t('csv.hint')}</p>

        <label
          className={dragging ? 'drop-zone over' : 'drop-zone'}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => take(event.target.files?.[0] ?? null)}
          />
          {file ? file.name : t('csv.dropZone')}
        </label>

        <ul className="csv-modes">
          {MODES.map((name) => {
            const off = name === 'sync' && parsed && !parsed.hasIds
            return (
              <li key={name}>
                <label className={off ? 'checkbox disabled' : 'checkbox'}>
                  <input
                    type="radio"
                    name="import-mode"
                    value={name}
                    checked={mode === name}
                    disabled={off}
                    onChange={() => setMode(name)}
                  />
                  <b>{t(`csv.mode.${name}`)}</b>
                  <span className="hint">
                    {off ? t('csv.mode.syncNeedsIds') : t(`csv.mode.${name}Hint`)}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>

        {error && <p className="error">{error}</p>}

        {cost && !refused && (
          <div className={losing ? 'csv-cost losing' : 'csv-cost'}>
            <p>
              {t(`csv.plan.${mode}`, {
                create: cost.create,
                update: cost.update,
                delete: cost.delete,
              })}
            </p>

            {cost.delete > 0 &&
              (losing ? (
                <>
                  <p className="error">
                    {t('csv.loss', {
                      lessons: cost.delete_lessons,
                      content: cost.with_content,
                      attachments: cost.with_attachments,
                    })}
                    {cost.files_lost > 0 && ` ${t('csv.filesLost', {
                      count: cost.files_lost,
                    })}`}
                  </p>

                  {cost.delete_with_content.length > 0 && (
                    <>
                      <button
                        type="button"
                        className="link"
                        onClick={() => setExpanded(!expanded)}
                      >
                        {t(expanded ? 'csv.hideLost' : 'csv.showLost')}
                      </button>
                      {expanded && (
                        <ul className="csv-lost">
                          {cost.delete_with_content.map((row) => (
                            <li key={row.id}>
                              {row.title}
                              {row.has_content && <span className="mark">📝</span>}
                              {row.has_attachments && <span className="mark">📎</span>}
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}

                  <label className="checkbox danger">
                    <input
                      type="checkbox"
                      checked={agreed}
                      onChange={(event) => setAgreed(event.target.checked)}
                    />
                    {t('csv.confirmLoss', { count: cost.with_content })}
                  </label>
                </>
              ) : (
                <p className="hint">{t('csv.deleteOnlyTitles')}</p>
              ))}
          </div>
        )}

        {refused && (
          <ul className="csv-warnings">
            <li className="error">{t('csv.refused')}</li>
            {cost.errors.slice(0, 5).map((problem, index) => (
              <li key={`${problem.code}-${index}`} className="error">
                {t(`errors.${problem.code}`, {
                  ...problem.params,
                  defaultValue: problem.detail,
                })}
              </li>
            ))}
          </ul>
        )}

        {parsed && (
          <>
            <p className="hint">
              {t('csv.parsed', {
                rows: parsed.rows.length,
                sections: parsed.rows.filter((row) => row.is_section).length,
                lessons: parsed.rows.filter((row) => !row.is_section).length,
              })}
              {parsed.rows.length > PREVIEW_LIMIT &&
                t('csv.previewLimit', { limit: PREVIEW_LIMIT })}
            </p>

            <ul className="csv-preview">
              {preview.map((row, index) => (
                <li
                  key={`${index}-${row.title}`}
                  className={row.is_section ? 'section' : 'lesson'}
                >
                  <span className="badge">
                    {row.is_section ? t('csv.section') : t('csv.lesson')}
                  </span>
                  {row.title}
                  {row.note && <span className="hint">{row.note}</span>}
                </li>
              ))}
            </ul>

            {parsed.warnings.length > 0 && (
              <ul className="csv-warnings">
                {parsed.warnings.slice(0, 5).map((warning) => (
                  <li key={`${warning.code}-${warning.params.row}`} className="hint">
                    {t(`warnings.${warning.code}`, warning.params)}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={blocked}>
            {t('csv.submit')}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
