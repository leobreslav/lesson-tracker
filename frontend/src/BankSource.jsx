import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import Basket from './Basket'
import Markdown from './Markdown'
import Modal from './Modal'
import Pick from './Pick'
import { fetchSource, fillSource, importFileIntoSource, importIntoSource } from './api'
import { taken } from './basket'

/**
 * Одна книга: оглавление и задачи раздела.
 *
 * Главный путь — **номер**: учитель помнит «§14, №6», и поле номера стоит в
 * шапке и прыгает к задаче, минуя оглавление вовсе. Оглавление для другого
 * случая: «покажи, что есть в теме», когда номера не помнят.
 *
 * Оглавление рисуется отступом, а не деревом с перетаскиванием: структура
 * книги **дана**, мы её переписываем, а не проектируем.
 */
export default function BankSource() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  // '' — вся книга, 'none' — вне разделов, число — раздел.
  const [section, setSection] = useState('')
  const [label, setLabel] = useState('')
  const [picked, setPicked] = useState(taken())
  // массовый импорт: матрица из буфера или файл
  const [importing, setImporting] = useState(null) // {text, preview}
  const [error, setError] = useState(null)
  const [filling, setFilling] = useState(null) // {kind: 'outline'|'problems', text}
  const [busy, setBusy] = useState(false)

  const load = useCallback(
    (params) =>
      fetchSource(id, params)
        .then(setData)
        .catch((problem) => setError(problem.message)),
    [id],
  )

  useEffect(() => {
    load({ section, label })
  }, [load, section, label])

  const fill = async () => {
    setBusy(true)
    setError(null)
    try {
      await fillSource(id,
        filling.kind === 'outline'
          ? { outline: filling.text }
          : {
              problems: filling.text,
              // «вся книга» и «вне разделов» — это не раздел, и класть
              // вписанное некуда, кроме как вне глав
              section: typeof section === 'number' ? section : null,
            },
      )
      setFilling(null)
      await load({ section, label })
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return null

  return (
    <main className="page wide">
      <header className="page-header spread">
        <div>
          <h1>{data.title}</h1>
          <p className="hint">
            <Link to="/bank">{t('bank.title')}</Link>
            {data.author && ` · ${data.author}`} · {t(`bank.levels.${data.level}`)}
          </p>
        </div>

        {/* номер — это адрес: главный способ дотянуться до задачи */}
        <div className="row middle">
          <label className="field">
            <span>{t('bank.number')}</span>
            <input
              value={label}
              placeholder="14а"
              onChange={(event) => setLabel(event.target.value.trim())}
            />
          </label>
          {data.may_edit && (
            <>
              <button
                type="button"
                className="secondary"
                onClick={() => setFilling({ kind: 'outline', text: '' })}
              >
                {t('bank.pasteOutline')}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setFilling({ kind: 'problems', text: '' })}
              >
                {t('bank.pasteProblems')}
              </button>
              {/* массовый импорт: та же книга, но приходит таблицей — из
                  чужой системы, из файла, из Excel */}
              <button
                type="button"
                className="secondary"
                onClick={() => setImporting({ text: '', preview: null })}
              >
                {t('bank.import.open')}
              </button>
              <label className="link-button">
                {t('bank.import.file')}
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  hidden
                  onChange={async (event) => {
                    const chosen = event.target.files[0]
                    if (!chosen) return
                    setBusy(true)
                    try {
                      await importFileIntoSource(id, chosen)
                      await load({ section, label })
                    } catch (problem) {
                      setError(problem.message)
                    } finally {
                      setBusy(false)
                      event.target.value = ''
                    }
                  }}
                />
              </label>
            </>
          )}
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <Basket picked={picked} onChange={setPicked} />

      <div className="bank-columns">
        <section className="panel outline">
          <h3>{t('bank.outline')}</h3>
          {data.outline.length === 0 ? (
            <p className="hint">{t('bank.noOutline')}</p>
          ) : (
            <ul>
              <li>
                <button
                  type="button"
                  className={section === '' ? 'link active' : 'link'}
                  onClick={() => setSection('')}
                >
                  {t('bank.wholeBook')}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className={section === 'none' ? 'link active' : 'link'}
                  onClick={() => setSection('none')}
                >
                  {t('bank.outsideSections')}
                </button>
              </li>
              {data.outline.map((row) => (
                <li key={row.id} style={{ paddingLeft: `${row.depth}rem` }}>
                  <button
                    type="button"
                    className={section === row.id ? 'link active' : 'link'}
                    onClick={() => {
                      setLabel('')
                      setSection(row.id)
                    }}
                  >
                    {row.title}
                  </button>
                  <span className="hint"> {row.problems}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel problems">
          {data.entries.length === 0 ? (
            <p className="hint">{t('bank.noProblems')}</p>
          ) : (
            <ul className="problem-list">
              {data.entries.map((entry) => (
                <li key={entry.id}>
                  <span className="label">
                    <Pick id={entry.problem} picked={picked} onChange={setPicked} />
                    <Link to={`/bank/problem/${entry.problem}`}>
                      {entry.label || '—'}
                    </Link>
                  </span>
                  <span className="text">
                    <Markdown text={entry.text} />
                  </span>
                  <span className="hint">
                    {/* чьё условие: от этого зависит, что с ним можно
                        сделать, а по строке этого иначе не понять */}
                    {entry.level !== 'personal' && (
                      <>{t(`bank.levels.${entry.level}`)} · </>
                    )}
                    {entry.retired && <>{t('bank.retired')} · </>}
                    {entry.solutions > 0 &&
                      t('bank.solutionCount', { count: entry.solutions })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {importing && (
        <Modal title={t('bank.import.title')} onClose={() => setImporting(null)}>
          <p className="hint">{t('bank.import.hint')}</p>
          <textarea
            autoFocus
            rows="10"
            value={importing.text}
            onChange={(event) =>
              setImporting({ text: event.target.value, preview: null })
            }
          />

          {importing.preview && (
            <p className={importing.preview.errors.length ? 'error' : 'hint'}>
              {importing.preview.errors.length
                ? importing.preview.errors.join(' · ')
                : t('bank.import.counted', importing.preview)}
            </p>
          )}

          <div className="row">
            <button
              type="button"
              className="secondary"
              disabled={busy || !importing.text.trim()}
              onClick={async () => {
                try {
                  const answer = await importIntoSource(id, {
                    rows: rowsOf(importing.text),
                    preview: true,
                  })
                  setImporting({ ...importing, preview: answer })
                } catch (problem) {
                  setError(problem.message)
                }
              }}
            >
              {t('bank.import.check')}
            </button>
            <button
              type="button"
              disabled={busy || !importing.text.trim()}
              onClick={async () => {
                setBusy(true)
                try {
                  await importIntoSource(id, { rows: rowsOf(importing.text) })
                  setImporting(null)
                  await load({ section, label })
                } catch (problem) {
                  setError(problem.message)
                } finally {
                  setBusy(false)
                }
              }}
            >
              {t('bank.import.do')}
            </button>
          </div>
        </Modal>
      )}

      {filling && (
        <Modal
          onClose={() => setFilling(null)}
          title={t(filling.kind === 'outline' ? 'bank.pasteOutline' : 'bank.pasteProblems')}
        >
          <p className="hint">
            {t(filling.kind === 'outline' ? 'bank.outlineHint' : 'bank.problemsHint')}
          </p>
          <textarea
            rows="12"
            value={filling.text}
            onChange={(event) => setFilling({ ...filling, text: event.target.value })}
          />
          <div className="actions">
            <button type="button" disabled={busy || !filling.text.trim()} onClick={fill}>
              {t('common.save')}
            </button>
          </div>
        </Modal>
      )}
    </main>
  )
}

/**
 * Вставленная таблица → матрица ячеек.
 *
 * Excel кладёт в буфер TSV, и разбирает его браузер — на сервер уезжает уже
 * матрица. Второго угадывания разделителя нигде нет: у файла его определяет
 * серверный разбор, у вставки разделитель известен.
 */
const rowsOf = (text) =>
  text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => line.split('\t'))
