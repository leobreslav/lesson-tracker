import { useState } from 'react'
import Modal from './Modal'
import { decodeCsv, parsePlanCsv } from './planCsv'

const PREVIEW_LIMIT = 20

/** Импорт плана из CSV: файл, режим и предпросмотр разбора. */
export default function ImportDialog({ busy, onSubmit, onClose }) {
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
      // разбираем прямо здесь: пользователь должен увидеть, что распозналось
      setParsed(parsePlanCsv(decodeCsv(await chosen.arrayBuffer())))
    } catch {
      setError('Не удалось прочитать файл — нужен текстовый CSV.')
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
        <h3>Импорт плана из CSV</h3>
        <p className="hint">
          Два столбца: тема и урок, третий — заметка. Тема может стоять
          отдельной строкой или повторяться в каждой строке урока.
        </p>

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
          {file ? file.name : 'Перетащите файл сюда или выберите'}
        </label>

        <div className="row">
          <label className="checkbox">
            <input
              type="radio"
              name="import-mode"
              checked={mode === 'replace'}
              onChange={() => setMode('replace')}
            />
            заменить план
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name="import-mode"
              checked={mode === 'append'}
              onChange={() => setMode('append')}
            />
            добавить в конец
          </label>
        </div>

        {mode === 'replace' && (
          <p className="error">Текущий план класса будет удалён целиком.</p>
        )}

        {error && <p className="error">{error}</p>}

        {parsed && (
          <>
            <p className="hint">
              Распознано строк: {parsed.rows.length} (тем{' '}
              {parsed.rows.filter((row) => row.is_section).length}, уроков{' '}
              {parsed.rows.filter((row) => !row.is_section).length}).
              {parsed.rows.length > PREVIEW_LIMIT &&
                ` Ниже первые ${PREVIEW_LIMIT}.`}
            </p>

            <ul className="csv-preview">
              {preview.map((row, index) => (
                <li
                  key={`${index}-${row.title}`}
                  className={row.is_section ? 'section' : 'lesson'}
                >
                  <span className="badge">{row.is_section ? 'тема' : 'урок'}</span>
                  {row.title}
                  {row.note && <span className="hint">{row.note}</span>}
                </li>
              ))}
            </ul>

            {parsed.warnings.length > 0 && (
              <ul className="csv-warnings">
                {parsed.warnings.slice(0, 5).map((warning) => (
                  <li key={warning} className="hint">
                    {warning}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        <div className="actions">
          <button type="submit" disabled={busy || !file || !parsed?.rows.length}>
            Импортировать
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            Отмена
          </button>
        </div>
      </form>
    </Modal>
  )
}
