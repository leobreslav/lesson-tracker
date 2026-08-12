import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { decodeCsv, parsePlanCsv } from './planCsv'

const PREVIEW_LIMIT = 20

/** Importing a plan from CSV: the file, the mode and a parse preview. */
export default function ImportDialog({ busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [file, setFile] = useState(null)
  const [mode, setMode] = useState('replace')
  const [parsed, setParsed] = useState(null) // {rows, warnings}
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)

  const take = async (chosen) => {
    setError(null)
    setFile(chosen)
    setParsed(null)
    if (!chosen) return

    try {
      // parsed right here: the person has to see what was recognised
      setParsed(parsePlanCsv(decodeCsv(await chosen.arrayBuffer())))
    } catch {
      setError(t('csv.unreadable'))
    }
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files?.[0] ?? null)
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    if (file) onSubmit({ file, mode })
  }

  const preview = parsed?.rows.slice(0, PREVIEW_LIMIT) ?? []

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

        <div className="row">
          <label className="checkbox">
            <input
              type="radio"
              name="import-mode"
              checked={mode === 'replace'}
              onChange={() => setMode('replace')}
            />
            {t('csv.modeReplace')}
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="import-mode"
              checked={mode === 'append'}
              onChange={() => setMode('append')}
            />
            {t('csv.modeAppend')}
          </label>
        </div>

        {mode === 'replace' && (
          <p className="error">{t('csv.replaceWarning')}</p>
        )}

        {error && <p className="error">{error}</p>}

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
          <button type="submit" disabled={busy || !file || !parsed?.rows.length}>
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
