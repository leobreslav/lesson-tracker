import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import MathText from './MathText'
import { fetchProposals, resolveProposal, sayOnProposal } from './api'

/**
 * Предложения: очередь разбора и свои сообщения.
 *
 * Два списка на одном экране, и это не смешение: «мои» отвечает на «дошло
 * ли», «на разбор» — на «что от меня ждут». Человек бывает и тем и другим
 * разом (администратор школы тоже находит опечатки в общем каталоге), и
 * разводить это по адресам значило бы заставлять его ходить в два места.
 *
 * Отказ требует слов — кнопка не нажимается, пока не написан ответ. Молчаливое
 * «отклонено» это загадка, а не ответ; то же правило, что у возврата плана
 * методистом.
 */
export default function Proposals() {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [answers, setAnswers] = useState({})
  const [notes, setNotes] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(
    () =>
      fetchProposals()
        .then(setData)
        .catch((problem) => setError(problem.message)),
    [],
  )

  useEffect(() => {
    load()
  }, [load])

  const run = async (what) => {
    setBusy(true)
    setError(null)
    try {
      await what
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return null

  const card = (one, resolving) => (
    <li key={one.id} className="panel">
      <p>
        <b>{t(`propose.kinds.${one.kind}`)}</b>
        {' · '}
        <span className="hint">
          {t(`bank.levels.${one.level}`)}
          {one.author && ` · ${one.author}`}
          {' · '}
          {t(`propose.states.${one.state}`)}
        </span>
      </p>

      {one.about && (
        <p className="hint">
          <MathText text={one.about} />
        </p>
      )}

      <p>{one.text}</p>
      {one.suggested && (
        <blockquote className="statement-stem">
          <MathText text={one.suggested} />
        </blockquote>
      )}

      {one.answer && <p className="hint">{t('propose.answered', { answer: one.answer })}</p>}

      <ul className="hint">
        {one.notes.map((note) => (
          <li key={note.id}>
            {note.author}: {note.text}
          </li>
        ))}
      </ul>

      <div className="row">
        <label className="field">
          <span>{t('propose.reply')}</span>
          <input
            value={notes[one.id] || ''}
            onChange={(event) =>
              setNotes({ ...notes, [one.id]: event.target.value })
            }
          />
        </label>
        <button
          type="button"
          className="secondary"
          disabled={busy || !(notes[one.id] || '').trim()}
          onClick={() =>
            run(sayOnProposal(one.id, notes[one.id]).then(() => setNotes({ ...notes, [one.id]: '' })))
          }
        >
          {t('propose.say')}
        </button>
      </div>

      {resolving && one.state === 'pending' && (
        <div className="row">
          <label className="field">
            <span>{t('propose.answer')}</span>
            <input
              value={answers[one.id] || ''}
              onChange={(event) =>
                setAnswers({ ...answers, [one.id]: event.target.value })
              }
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              run(
                resolveProposal(one.id, {
                  state: 'accepted',
                  answer: answers[one.id] || '',
                  // вид нового тега спрашивается тут же: словарь разложен по
                  // видам, и это решение того, кто его ведёт
                  tag_kind: answers[`kind-${one.id}`],
                }),
              )
            }
          >
            {t('propose.accept')}
          </button>
          {one.kind === 'tag' && !one.tag && (
            <select
              aria-label={t('propose.tagKind')}
              value={answers[`kind-${one.id}`] || ''}
              onChange={(event) =>
                setAnswers({ ...answers, [`kind-${one.id}`]: event.target.value })
              }
            >
              <option value="">{t('propose.tagKind')}</option>
              <option value="subject">{t('propose.tagKinds.subject')}</option>
              <option value="object">{t('propose.tagKinds.object')}</option>
              <option value="task">{t('propose.tagKinds.task')}</option>
              <option value="theorem">{t('propose.tagKinds.theorem')}</option>
              <option value="method">{t('propose.tagKinds.method')}</option>
            </select>
          )}
          <button
            type="button"
            className="secondary"
            disabled={busy || !(answers[one.id] || '').trim()}
            onClick={() =>
              run(
                resolveProposal(one.id, {
                  state: 'declined',
                  answer: answers[one.id] || '',
                }),
              )
            }
          >
            {t('propose.decline')}
          </button>
        </div>
      )}
    </li>
  )

  return (
    <main className="page wide">
      <header className="page-header spread">
        <h1>{t('propose.listTitle')}</h1>
        <Link to="/bank">{t('bank.title')}</Link>
      </header>

      {error && <p className="error">{error}</p>}

      {data.waiting.length > 0 && (
        <>
          <h2>{t('propose.waiting', { count: data.waiting.length })}</h2>
          <ul className="proposal-list">{data.waiting.map((one) => card(one, true))}</ul>
        </>
      )}

      <h2>{t('propose.mine')}</h2>
      {data.mine.length === 0 ? (
        <p className="hint">{t('propose.noneMine')}</p>
      ) : (
        <ul className="proposal-list">{data.mine.map((one) => card(one, false))}</ul>
      )}
    </main>
  )
}
