import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import Basket from './Basket'
import Markdown from './Markdown'
import Modal from './Modal'
import Pick from './Pick'
import { fetchSource, fillSource } from './api'
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
                  {entry.solutions > 0 && (
                    <span className="hint">
                      {t('bank.solutionCount', { count: entry.solutions })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

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
