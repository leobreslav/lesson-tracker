import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from './Modal'
import { previewPlanFile, previewPlanRows } from './api'
import { decodeCsv, parsePlanCsv } from './planCsv'
import PasteGrid from './PasteGrid'

/** Книгу здесь не читают: её разбирает сервер. */
const isWorkbook = (file) => /\.xlsx$/i.test(file?.name ?? '')

const PREVIEW_LIMIT = 20
const MODES = ['sync', 'append', 'replace']
const SOURCES = ['file', 'paste']

/** Пустая строка сетки в разбор не едет: это место, а не урок. */
const filled = (rows) => rows.filter((row) => row.some((cell) => cell.trim()))

/**
 * Importing a plan from a file: the file, the mode and two previews.
 *
 * Форматов два, и различаются они только тем, кто читает файл. **CSV**
 * разбирается здесь же, в браузере: человек видит, как файл прочитан, ещё
 * до отправки, и негодный отклоняется без обращения к серверу. **xlsx**
 * читает openpyxl на сервере — тащить вторую библиотеку в бандл ради
 * предпросмотра незачем, — поэтому «как прочитано» приезжает вместе с
 * ценой, из `import-preview-xlsx`.
 *
 * Цену в обоих случаях считает сервер: только он знает, у каких уроков есть
 * содержание и на какие файлы больше никто не смотрит. Ради этого ответа
 * диалог и устроен так: replace уносит тела уроков и вложения вместе со
 * строками, а файл, потерявший последнюю ссылку, исчезает навсегда.
 */
export default function ImportDialog({ classId, busy, onSubmit, onClose }) {
  const { t } = useTranslation()
  const [source, setSource] = useState('file')
  const [rows, setRows] = useState([])
  const [file, setFile] = useState(null)
  const [mode, setMode] = useState('sync')
  const [parsed, setParsed] = useState(null) // {rows, errors, dataRows}
  const [cost, setCost] = useState(null) // the server's answer
  const [expanded, setExpanded] = useState(false)
  const [agreed, setAgreed] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)

  // у книги и у вставки id видит только сервер: читает он
  const syncable = parsed ? parsed.rows.some((row) => row.id) : cost?.syncable
  const pasted = filled(rows)
  const ready = source === 'file' ? Boolean(file) : pasted.length > 0

  const take = async (chosen) => {
    setError(null)
    setFile(chosen)
    setParsed(null)
    setCost(null)
    setAgreed(false)
    if (!chosen) return

    if (isWorkbook(chosen)) return // книгу читает сервер, здесь читать нечем

    try {
      const result = parsePlanCsv(decodeCsv(await chosen.arrayBuffer()))
      setParsed(result)
      // синхронизировать не с чем: ни одной строки с id
      if (mode === 'sync' && !result.rows.some((row) => row.id)) setMode('append')
    } catch {
      setError(t('csv.unreadable'))
    }
  }

  /*
   * Цена спрашивается заново на каждую смену режима: replace и sync теряют
   * совершенно разное.
   *
   * У вставки к этому добавляется правка ячеек, поэтому запрос отложен на
   * полсекунды: печатать название и слать запрос на каждую букву незачем.
   */
  useEffect(() => {
    if (!ready || parsed?.errors.length) return undefined
    if (source === 'file' && !parsed && !isWorkbook(file)) return undefined

    let current = true
    setCost(null)
    setAgreed(false)

    const ask = () =>
      (source === 'file'
        ? previewPlanFile(classId, file, mode)
        : previewPlanRows(classId, pasted, mode)
      )
        .then((result) => current && setCost(result))
        .catch((err) => {
          if (!current) return
          setCost(null)
          setError(err.message)
        })

    if (source === 'file') {
      ask()
      return () => {
        current = false
      }
    }

    const timer = setTimeout(ask, 500)
    return () => {
      current = false
      clearTimeout(timer)
    }
    // сама матрица в зависимостях лишняя: её содержимое меняется на каждую
    // букву, а строка из неё — то, что действительно уедет на сервер
  }, [classId, source, file, parsed, mode, JSON.stringify(pasted)])

  /*
   * Синхронизировать не с чем — переключаемся сами.
   *
   * У CSV это видно на клиенте и делается сразу при выборе файла, а у
   * книги и у вставки про id знает только сервер. Без этого человек,
   * вставивший свой план из Excel (там id нет и быть не может), первым
   * делом видел красный отказ вместо чисел.
   */
  useEffect(() => {
    if (cost?.syncable === false && mode === 'sync') setMode('append')
  }, [cost, mode])

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files?.[0] ?? null)
  }

  const preview = parsed?.rows.slice(0, PREVIEW_LIMIT) ?? []
  const losing = Boolean(cost && (cost.with_content || cost.with_attachments))
  const problems = parsed?.errors.length ? parsed.errors : cost?.errors ?? []
  const refused = problems.length > 0
  // an explicit tick, not just a click on a button: this is the one place
  // where work disappears without a copy anywhere
  const blocked =
    busy || refused || !cost || !cost.lessons || (losing && !agreed)

  const handleSubmit = (event) => {
    event.preventDefault()
    if (blocked) return
    if (source === 'file' && file) onSubmit({ file, mode })
    if (source === 'paste') onSubmit({ rows: pasted, mode })
  }

  const changeSource = (name) => {
    setSource(name)
    setError(null)
    setCost(null)
    setParsed(null)
    setAgreed(false)
  }

  return (
    <Modal
      onClose={onClose}
      title={t('csv.title')}
      // сетке нужна ширина: три колонки в узком окне обрезают названия
      className={source === 'paste' ? 'paste-window' : ''}
    >
      <form onSubmit={handleSubmit}>
        {/* Источника два, а дальше всё общее: режим, предпросмотр, цена.
            Вставка нужна затем, чтобы не возиться с файлами вовсе —
            скопировали кусок листа и вставили. */}
        <span className="chips" role="group" aria-label={t('csv.source.label')}>
          {SOURCES.map((name) => (
            <button
              key={name}
              type="button"
              className={name === source ? 'chip active' : 'chip'}
              aria-pressed={name === source}
              onClick={() => changeSource(name)}
            >
              {t(`csv.source.${name}`)}
            </button>
          ))}
        </span>

        {source === 'paste' && (
          <>
            <p className="hint">{t('csv.paste.about')}</p>
            <PasteGrid rows={rows} onChange={setRows} disabled={busy} />
          </>
        )}

        {source === 'file' && (
          <>
        <p className="hint">{t('csv.hint', { header: 'id,Тема,Урок' })}</p>

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
            accept=".xlsx,.csv,text/csv"
            onChange={(event) => take(event.target.files?.[0] ?? null)}
          />
          {file ? file.name : t('csv.dropZone')}
        </label>
          </>
        )}

        <ul className="csv-modes">
          {MODES.map((name) => {
            // у книги ответ приходит с сервера, поэтому ждём его: пока
            // syncable неизвестен, режим не гасим
            const off = name === 'sync' && syncable === false
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
                    {off ? t('csv.mode.nothingToSync') : t(`csv.mode.${name}Hint`)}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>

        {error && <p className="error">{error}</p>}

        {refused && (
          <ul className="csv-warnings">
            <li className="error">{t('csv.refused')}</li>
            {problems.slice(0, 5).map((problem, index) => (
              <li key={`${problem.code}-${index}`} className="error">
                {t(`errors.${problem.code}`, {
                  ...problem.params,
                  defaultValue: problem.detail,
                })}
              </li>
            ))}
            {problems.length > 5 && (
              <li className="hint">
                {t('csv.moreProblems', { count: problems.length - 5 })}
              </li>
            )}
          </ul>
        )}

        {/* как файл прочитан и что из этого выйдет — одной строкой */}
        {(parsed || cost) && !refused && (
          <p className="hint">
            {t('csv.readAs', {
              rows: cost ? cost.rows : parsed.dataRows,
              lessons: cost
                ? cost.lessons
                : parsed.rows.filter((row) => !row.is_section).length,
              sections: cost
                ? cost.sections
                : parsed.rows.filter((row) => row.is_section).length,
            })}
            {cost &&
              t('csv.willDo', {
                create: cost.create,
                update: cost.update,
                delete: cost.delete,
              })}
            {cost?.with_content > 0 &&
              t('csv.ofThemWithContent', { count: cost.with_content })}
          </p>
        )}

        {cost?.sheets_ignored > 0 && (
          <p className="hint">
            {t('csv.sheetUsed', {
              sheet: cost.sheet,
              count: cost.sheets_ignored,
            })}
          </p>
        )}

        {cost?.create_sections > 0 && mode === 'sync' && (
          <p className="hint">
            {t('csv.newSections', { count: cost.create_sections })}
          </p>
        )}

        {cost && !refused && cost.delete > 0 && (
          <div className={losing ? 'csv-cost losing' : 'csv-cost'}>
            {losing ? (
              <>
                <p className="error">
                  {t('csv.loss', {
                    lessons: cost.delete_lessons,
                    content: cost.with_content,
                    attachments: cost.with_attachments,
                  })}
                  {cost.files_lost > 0 &&
                    ` ${t('csv.filesLost', { count: cost.files_lost })}`}
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
            )}
          </div>
        )}

        {parsed && !refused && (
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
            {parsed.rows.length > PREVIEW_LIMIT && (
              <li className="hint">
                {t('csv.previewLimit', { limit: PREVIEW_LIMIT })}
              </li>
            )}
          </ul>
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
