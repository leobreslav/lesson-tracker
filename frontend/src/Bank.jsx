import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import EmptyState from './EmptyState'
import { createSource, fetchSources } from './api'

/**
 * Задачник: полка источников.
 *
 * Полок будет три — источники, темы и папки, — и это разные способы дотянуться
 * до одной и той же задачи. Источники стоят первыми, потому что учитель думает
 * «Мордкович, §14, №6»: книга и номер, а не дерево тем.
 *
 * Уровень владения показан у каждой книги: системная, школьная или своя. Без
 * этого непонятно, почему у одной есть карандаш, а у другой нет.
 */
export default function Bank() {
  const { t } = useTranslation()
  const [sources, setSources] = useState(null)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(null) // {title, author, level}
  const [busy, setBusy] = useState(false)

  const load = () =>
    fetchSources()
      .then((answer) => setSources(answer.sources))
      .catch((problem) => setError(problem.message))

  useEffect(() => {
    load()
  }, [])

  const add = async () => {
    setBusy(true)
    setError(null)
    try {
      await createSource(adding)
      setAdding(null)
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!sources) return null

  const shelves = [
    ['system', sources.filter((one) => one.level === 'system')],
    ['school', sources.filter((one) => one.level === 'school')],
    ['personal', sources.filter((one) => one.level === 'personal')],
  ]

  return (
    <main className="page wide">
      <header className="page-header spread">
        <h1>{t('bank.title')}</h1>
        <button type="button" onClick={() => setAdding({ title: '', author: '', level: 'personal' })}>
          {t('bank.addSource')}
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {adding && (
        <section className="panel">
          <div className="row">
            <label className="field">
              <span>{t('bank.sourceTitle')}</span>
              <input
                value={adding.title}
                onChange={(event) => setAdding({ ...adding, title: event.target.value })}
              />
            </label>
            <label className="field">
              <span>{t('bank.sourceAuthor')}</span>
              <input
                value={adding.author}
                onChange={(event) => setAdding({ ...adding, author: event.target.value })}
              />
            </label>
            <label className="field">
              <span>{t('bank.level')}</span>
              <select
                value={adding.level}
                onChange={(event) => setAdding({ ...adding, level: event.target.value })}
              >
                <option value="personal">{t('bank.levels.personal')}</option>
                <option value="school">{t('bank.levels.school')}</option>
                <option value="system">{t('bank.levels.system')}</option>
              </select>
            </label>
            <button type="button" disabled={busy || !adding.title.trim()} onClick={add}>
              {t('common.add')}
            </button>
            <button type="button" className="secondary" onClick={() => setAdding(null)}>
              {t('common.cancel')}
            </button>
          </div>
        </section>
      )}

      {sources.length === 0 && !adding ? (
        <EmptyState
          title={t('bank.empty.title')}
          hint={t('bank.empty.hint')}
          action={t('bank.addSource')}
          onAction={() => setAdding({ title: '', author: '', level: 'personal' })}
        />
      ) : (
        shelves.map(([level, items]) =>
          items.length === 0 ? null : (
            <section className="panel" key={level}>
              <h3>{t(`bank.levels.${level}`)}</h3>
              <ul className="source-list">
                {items.map((source) => (
                  <li key={source.id}>
                    <Link to={`/bank/source/${source.id}`}>{source.title}</Link>
                    {source.author && <span className="hint"> {source.author}</span>}
                    <span className="hint count">
                      {t('bank.problemCount', { count: source.problems })}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ),
        )
      )}
    </main>
  )
}
