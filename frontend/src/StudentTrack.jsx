import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import MathText from './MathText'
import { fetchTrack } from './api'
import { shortDate } from './dates'

/**
 * След ученика: каждое условие, которое он решал, и чем это кончилось.
 *
 * Собран **по условиям**, а не по работам, и в этом весь смысл: задача,
 * спрошенная в пятом классе и в девятом, — одна строка с двумя встречами.
 * За годы это и складывается в ответ на вопрос «что этот человек решал», а не
 * «какие работы ему задавали».
 *
 * Права приходят с сервера, а не решаются тут: учителю отдаётся след по его
 * курсам, ученику — свой целиком, чужой не отдаётся вовсе.
 */
export default function StudentTrack() {
  const { id } = useParams()
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchTrack(id)
      .then(setData)
      .catch((problem) => setError(problem.message))
  }, [id])

  if (error) return <main className="page"><p className="error">{error}</p></main>
  if (!data) return null

  return (
    <main className="page wide">
      <header className="page-header">
        <h1>{t('track.title')}</h1>
      </header>

      <section className="panel">
        <p className="hint">
          {t('track.summary', {
            problems: data.summary.problems,
            attempts: data.summary.attempts,
            repeated: data.summary.repeated,
          })}
        </p>
      </section>

      {data.track.length === 0 ? (
        <p className="hint">{t('track.empty')}</p>
      ) : (
        <ul className="problem-list">
          {data.track.map((row) => (
            <li key={row.problem}>
              <span className="label">{row.times}×</span>
              <span className="text">
                {row.stem && (
                  <span className="hint">
                    <MathText text={row.stem} />{' '}
                  </span>
                )}
                <MathText text={row.text} />
                <span className="hint">
                  {row.works.map((one) => `${one.title} · ${one.course}`).join(' · ')}
                  {' · '}
                  {shortDate(row.last.slice(0, 10))}
                </span>
              </span>
              {row.right > 0 && <span className="tag">{t('track.right')}</span>}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
