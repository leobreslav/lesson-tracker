import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import AnalogueDialog from './AnalogueDialog'
import Collapsible from './Collapsible'
import CopyToShelf from './CopyToShelf'
import Markdown from './Markdown'
import TagStrip from './TagStrip'
import { shortDate } from './dates'
import { createSolution, fetchProblem, fetchTags, leaveFamily, saveProblem } from './api'

/**
 * Условие целиком: разборы, где встречается, аналоги.
 *
 * Решения читают **рядом с условием**, поэтому своей страницы у них нет: они
 * разворачиваются здесь же. А «встречается в» — единственное место, где видно,
 * что задача одна, а книг несколько: копий у неё нет, и это важно показать.
 */
export default function BankProblem() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [copying, setCopying] = useState(false)
  const [analogue, setAnalogue] = useState(false)
  // Словарь общий на всю страницу: он один и тот же для условия и всех разборов.
  const [vocabulary, setVocabulary] = useState([])
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(null) // текст условия
  const [adding, setAdding] = useState(null) // {title, text}

  const load = useCallback(
    () =>
      fetchProblem(id)
        .then(setData)
        .catch((problem) => setError(problem.message)),
    [id],
  )

  useEffect(() => {
    fetchTags()
      .then((answer) => setVocabulary(answer.tags))
      .catch(() => setVocabulary([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const run = async (task) => {
    setBusy(true)
    setError(null)
    try {
      await task()
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return null

  return (
    <main className="page">
      <header className="page-header">
        <h1>{t('bank.problem')}</h1>
        <p className="hint">
          <Link to="/bank">{t('bank.title')}</Link> · {t(`bank.levels.${data.level}`)}
          {data.created_by && ` · ${data.created_by}`}
        </p>
        <button type="button" className="secondary" onClick={() => setCopying(true)}>
          {t('bank.copy.title')}
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {copying && (
        <CopyToShelf
          problem={data.id}
          onClose={() => setCopying(false)}
          onDone={() => {
            setCopying(false)
            load()
          }}
        />
      )}

      {analogue && (
        <AnalogueDialog
          problem={data.id}
          onClose={() => setAnalogue(false)}
          onDone={() => {
            setAnalogue(false)
            load()
          }}
        />
      )}

      <section className="panel">
        {editing === null ? (
          <>
            <Markdown text={data.text} />
            {data.answer && (
              <p className="hint">{t('bank.answer', { answer: data.answer })}</p>
            )}
            <TagStrip
              tags={data.tags}
              vocabulary={vocabulary}
              kinds={['subject', 'object', 'task']}
              mayEdit={data.may_edit}
              target={{ problem: data.id }}
              onChange={load}
            />
            {data.may_edit && (
              <button type="button" className="link" onClick={() => setEditing(data.text)}>
                {t('common.edit')}
              </button>
            )}
          </>
        ) : (
          <>
            <textarea
              rows="6"
              value={editing}
              onChange={(event) => setEditing(event.target.value)}
            />
            <div className="actions">
              <button
                type="button"
                disabled={busy}
                onClick={() => run(async () => {
                  await saveProblem(id, { text: editing })
                  setEditing(null)
                })}
              >
                {t('common.save')}
              </button>
              <button type="button" className="secondary" onClick={() => setEditing(null)}>
                {t('common.cancel')}
              </button>
            </div>
          </>
        )}
      </section>

      {/* где её уже спрашивали: список коротких строк, а не таблица —
          отвечает он на один вопрос, «не задавал ли я это уже» */}
      {data.asked_in.length > 0 && (
        <section className="panel">
          <h3>{t('bank.askedIn')}</h3>
          <ul className="hint">
            {data.asked_in.map((row) => (
              <li key={row.work}>
                <Link to={`/works/${row.work}`}>{row.title}</Link> · {row.course} ·{' '}
                {shortDate(row.date)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* где встречается: задача одна, книг несколько — копий у неё нет */}
      {data.sources.length > 0 && (
        <section className="panel">
          <h3>{t('bank.foundIn')}</h3>
          <ul className="hint">
            {data.sources.map((source, index) => (
              <li key={index}>
                <Link to={`/bank/source/${source.id}`}>{source.title}</Link>
                {source.section && ` · ${source.section}`}
                {source.label && ` · №${source.label}`}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('bank.solutions')}</h3>
          <button
            type="button"
            className="secondary compact"
            disabled={busy}
            onClick={() => setAdding({ title: '', text: '' })}
          >
            {t('bank.addSolution')}
          </button>
        </div>

        {data.solutions.length === 0 && !adding && (
          <p className="hint">{t('bank.noSolutions')}</p>
        )}

        {data.solutions.map((solution) => (
          <Collapsible
            key={solution.id}
            name={`solution.${solution.id}`}
            title={solution.title || t('bank.solution')}
            note={`${t(`bank.levels.${solution.level}`)}${solution.author ? ` · ${solution.author}` : ''}`}
            openByDefault={false}
          >
            <Markdown text={solution.text} />
            <TagStrip
              tags={solution.tags}
              vocabulary={vocabulary}
              kinds={['subject', 'theorem', 'method']}
              mayEdit={solution.may_edit}
              target={{ solution: solution.id }}
              onChange={load}
            />
          </Collapsible>
        ))}

        {adding && (
          <div className="inline-form bare">
            <label className="field">
              <span>{t('bank.solutionTitle')}</span>
              <input
                value={adding.title}
                onChange={(event) => setAdding({ ...adding, title: event.target.value })}
              />
            </label>
            <textarea
              rows="6"
              value={adding.text}
              onChange={(event) => setAdding({ ...adding, text: event.target.value })}
            />
            <div className="actions">
              <button
                type="button"
                disabled={busy || !adding.text.trim()}
                onClick={() => run(async () => {
                  await createSolution({ problem: Number(id), ...adding })
                  setAdding(null)
                })}
              >
                {t('common.save')}
              </button>
              <button type="button" className="secondary" onClick={() => setAdding(null)}>
                {t('common.cancel')}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head spread">
          <h3>{t('bank.analogues')}</h3>
          <div className="row">
            <button type="button" className="secondary compact" onClick={() => setAnalogue(true)}>
              {t('bank.analogue.add')}
            </button>
            {data.analogues.length > 0 && data.may_edit && (
              <button
                type="button"
                className="link"
                onClick={() =>
                  leaveFamily(data.id)
                    .then(load)
                    .catch((trouble) => setError(trouble.message))
                }
              >
                {t('bank.analogue.leave')}
              </button>
            )}
          </div>
        </div>
        {data.analogues.length === 0 ? (
          <p className="hint">{t('bank.analogue.none')}</p>
        ) : (
          <ul className="problem-list">
            {data.analogues.map((one) => (
              <li key={one.id}>
                <Link className="label" to={`/bank/problem/${one.id}`}>
                  #{one.id}
                </Link>
                <span className="text">
                  <Markdown text={one.text} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}
